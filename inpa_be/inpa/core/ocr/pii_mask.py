"""Claude(국외) 전송 직전 신원식별정보 마스킹 — privacy-by-design.

PM 지시(2026-07-09, docs/superpowers/specs/2026-07-09-ai-pii-masking.md): AI 분석에
필요한 건 보장담보·금액·항목이지 이름·주민번호가 아니다. Claude 로 보내는 텍스트
"사본"에서만 신원식별자(주민등록번호/전화번호/이메일/식별 라벨에 바로 붙은 성명)를
보수적·정밀 패턴으로 마스킹한다. ★ 원본(text_lines)·우리 DB 레코드는 절대 변경하지
않는다 — 마스킹은 Claude 전송용 사본에만 적용된다(국외이전 개인정보 최소화, PIPA).

★ 담보명(암진단비 등)·금액·회사명·날짜·보험기간 등 분석에 필요한 데이터는 아래 패턴
(RRN/전화/이메일/라벨-근접 성명)에 매치되지 않으므로 절대 마스킹되지 않는다 — 과다
마스킹으로 담보 인식 정확도가 깨지는 것이 이 기능의 최대 리스크(spec §리스크 참조).
"""
import re

from inpa.core.ocr.ocrparsing import NOT_NAMES

# 주민등록번호: 완전형("690913-2123456") + 부분마스킹형("690913 - 2******") 모두 대응.
_RRN_PATTERN = re.compile(r'\d{6}\s*[-–]\s*[1-4][\d*]{6}')

# 휴대폰 번호: 01[016789] 접두(010/011/016/017/018/019) + 구분자(공백/./-) 허용.
_PHONE_PATTERN = re.compile(r'01[016789][-\s.]?\d{3,4}[-\s.]?\d{4}')

# 이메일: 표준형.
_EMAIL_PATTERN = re.compile(r'[\w.+-]+@[\w-]+\.[\w.-]+')

# 신원 라벨 바로 뒤(공백/콜론/줄바꿈 개재 허용)의 한글 2~4자 토큰만 마스킹 대상.
# 라벨이 앞에 없으면 담보명(예: 암진단비)·회사명 등은 이 패턴에 절대 매치되지 않는다.
# (긴 라벨을 먼저 배치 — "피보험자명"이 "피보험자"에 부분매칭되지 않도록 순서 유의.
#  구분자(공백/콜론/줄바꿈)는 별도 그룹으로 보존 — 이름 토큰만 지우고 줄 구조는
#  그대로 둔다: "계약자\n박진희" → "계약자\n***", 라인 수·나머지 텍스트 불변.)
_IDENTITY_NAME_PATTERN = re.compile(
    r'(피보험자명|계약자|피보험자|수익자|성명|가입자)([\s:：]*)([가-힣]{2,4})(?![가-힣])'
)


def _mask_name(match):
    label, sep, candidate = match.group(1), match.group(2), match.group(3)
    # ocrparsing._extract_person_name 이 이름 "추출"에 쓰는 것과 동일한 오탐 방지
    # 사전(NOT_NAMES)을 재사용 — "주민번호"·"보험기간" 같은 테이블 헤더/구조어가
    # 라벨 바로 뒤에 왔다고 이름으로 오인해 지우지 않는다(과다 마스킹 방지: 이런
    # 구조어는 어차피 신원정보가 아니므로 원문 그대로 두는 편이 더 정밀하다).
    if candidate in NOT_NAMES:
        return match.group(0)
    return f'{label}{sep}***'


def _strip_identity(text):
    """Claude 전송용 텍스트에서 신원식별자만 마스킹해 반환.

    문자열은 불변(immutable)이므로 인자로 받은 원본 text/그 출처(text_lines, DB
    레코드)는 이 함수 호출로 절대 변경되지 않는다 — 반환값만 Claude 전송에 쓴다.
    """
    if not text:
        return text
    masked = _RRN_PATTERN.sub('******-*******', text)
    masked = _PHONE_PATTERN.sub('010-****-****', masked)
    masked = _EMAIL_PATTERN.sub('***@***', masked)
    masked = _IDENTITY_NAME_PATTERN.sub(_mask_name, masked)
    return masked
