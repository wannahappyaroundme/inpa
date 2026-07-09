"""증권 파싱 정확도 다중검사 — Claude로 '원문 텍스트 ↔ 파싱·정규화 결과' 교차검증.

★ 목적(사용자 요구: 정확도가 가장 중요): 스캔/인식/분류 후 우리 표준 틀·담보표에 제대로 매핑됐는지를
  Claude(Opus)가 한 번 더 검토해 ①누락 담보 ②금액 오인식 ③오분류를 잡아낸다. = '다중 검사'.
  결과는 CustomerInsurance.verification 에 저장하고 응답에 포함(설계사 확인용 플래그).

★ 안전:
  - 인증 OCR 경로(InsuranceOcrViewSet) 전용. 무인증 셀프진단엔 미적용(비용 폭주 방지).
  - 실패(키 없음/패키지 없음/API 오류)는 격리 — 파싱 결과를 절대 깨뜨리지 않는다(None 반환).
  - 결정·판정이 아니라 '검토 플래그' 제공. 최종 확인·수정은 설계사.
"""
import logging

from django.conf import settings

from inpa.core.ocr.pii_mask import _strip_identity

logger = logging.getLogger(__name__)


def _serialize_coverages(ci):
    """ci 의 파싱된 담보 목록 → [(표준담보명, 보장금액)] (검증 프롬프트 입력용)."""
    rows = []
    for case in ci.case_list.all():
        std = [ad.name for ad in case.detail.analysis_detail.all()] or [case.detail.name]
        rows.append((' / '.join(std), case.assurance_amount))
    return rows


def verify_extraction(text_lines, ci):
    """원문 텍스트와 파싱 담보를 Claude로 교차검증. (result, usage) 튜플 반환.

    반환 형태:
      result: {checked: True, confidence: 'high'|'medium'|'low',
               issues: [str], missing: [str], note: str, model: str} | None(검증 불가/실패)
      usage:  message.usage(호출이 실제로 일어나 응답을 받은 경우) | None(호출 자체가 없었음).
        ★ 프리런치 #17: 과거엔 usage 를 버렸다(호출자가 log_claude_usage 에 None 을 항상
          하드코딩해 토큰이 0으로 찍히던 버그) — 이제 실제 usage 를 반환해 정확히 로깅한다.
    """
    api_key = getattr(settings, 'CLAUDE_API_KEY', '') or getattr(settings, 'ANTHROPIC_API_KEY', '')
    if not api_key:
        return None, None
    try:
        import anthropic
    except ImportError:
        return None, None

    coverages = _serialize_coverages(ci)
    cov_text = '\n'.join(f'- {name}: {amount}' for name, amount in coverages) or '(파싱된 담보 없음)'
    # ★ 2026-07-09 PM 지시: Claude 교차검증에도 동일 마스킹 적용(신원정보 국외 미전송).
    #   cov_text(담보명/금액)엔 애초에 신원 PII 가 없으므로 대상 아님 — source_text(원문)만.
    source_text = _strip_identity('\n'.join(text_lines))[:12000]  # 토큰 보호 상한

    system_prompt = (
        '당신은 보험증권 파싱 결과의 정확도를 검수하는 QA 도구입니다.\n'
        '주어진 [증권 원문]과 그로부터 추출·정규화된 [파싱 담보 목록]을 대조해, 파싱이 정확한지 교차검증하세요.\n'
        '## 점검 항목\n'
        '1) 원문에는 있으나 파싱 목록에서 누락된 담보(missing)\n'
        '2) 보장금액이 원문과 다르게 인식된 담보(issues)\n'
        '3) 담보가 엉뚱한 표준 담보로 분류된 경우(issues)\n'
        '## 규칙\n'
        '- 원문 텍스트에 실제로 있는 근거만 사용하라. 원문에 없는 내용을 지어내지 마라.\n'
        '- 확신이 낮으면 confidence 를 낮추되 추측성 단정은 피하라.\n'
        '- 반드시 아래 JSON 형식으로만 답하라(설명 산문 금지):\n'
        '{"confidence":"high|medium|low","issues":["..."],"missing":["..."],"note":"한줄요약"}'
    )
    user_prompt = f'[증권 원문]\n{source_text}\n\n[파싱 담보 목록]\n{cov_text}\n'

    model_id = getattr(settings, 'CLAUDE_MODEL_PARSE', 'claude-opus-4-8')
    try:
        client = anthropic.Anthropic(api_key=api_key, timeout=60.0, max_retries=2)
        msg = client.messages.create(
            model=model_id,
            max_tokens=1024,
            system=[{'type': 'text', 'text': system_prompt,
                     'cache_control': {'type': 'ephemeral'}}],
            messages=[{'role': 'user', 'content': user_prompt}],
        )
        usage = getattr(msg, 'usage', None)
        text = msg.content[0].text.strip()
        result = _parse_json(text)
        if result is None:
            return None, usage
        return {
            'checked': True,
            'confidence': result.get('confidence', 'medium'),
            'issues': result.get('issues', []) or [],
            'missing': result.get('missing', []) or [],
            'note': result.get('note', ''),
            'model': model_id,
        }, usage
    except Exception as e:  # 검증 실패는 파싱 결과에 영향 주지 않는다
        # 내용 미포함 로깅(LB#9) — 예외 타입만, 증권/응답 데이터 금지
        logger.warning('증권 교차검증 실패(파싱 결과 영향 없음): %s', type(e).__name__)
        return None, None


def _parse_json(text):
    """Claude 응답에서 JSON 객체 추출(코드펜스/잡텍스트 방어)."""
    import json
    import re
    try:
        return json.loads(text)
    except Exception:
        pass
    m = re.search(r'\{.*\}', text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            return None
    return None
