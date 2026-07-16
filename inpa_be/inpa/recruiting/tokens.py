from django.core import signing
from django.core.exceptions import ValidationError


RECRUITING_CHOICE_SALT = "inpa-recruiting-leader-choice"
RECRUITING_CHOICE_MAX_AGE_SECONDS = 60 * 10


def make_leader_choice_token(*, old_candidate_id, new_candidate_id):
    return signing.dumps(
        {
            "old_candidate_id": old_candidate_id,
            "new_candidate_id": new_candidate_id,
            "v": 1,
        },
        salt=RECRUITING_CHOICE_SALT,
        compress=True,
    )


def read_leader_choice_token(token):
    try:
        payload = signing.loads(
            token,
            salt=RECRUITING_CHOICE_SALT,
            max_age=RECRUITING_CHOICE_MAX_AGE_SECONDS,
        )
    except signing.BadSignature as exc:
        raise ValidationError("선택 시간이 지나 새 지원 링크에서 다시 확인해주세요.") from exc
    if not isinstance(payload, dict) or payload.get("v") != 1:
        raise ValidationError("선택 내용을 새 지원 링크에서 다시 확인해주세요.")
    try:
        return int(payload["old_candidate_id"]), int(payload["new_candidate_id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValidationError("선택 내용을 새 지원 링크에서 다시 확인해주세요.") from exc
