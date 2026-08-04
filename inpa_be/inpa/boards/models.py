"""게시판 & 커뮤니티 모델 (dev/17, dev/02 §10).

가시성 매트릭스 (dev/02 §0):
  Post / Comment / PostLike / PostAttachment  — 공유 (owner FK 없음)
  Report                                       — 신고자 본인 조회 + 관리자 처리
  Notice / Faq                                 — 공개읽기 + 관리자쓰기 (owner FK 없음)
  Inquiry / InquiryReply                       — 비공개 (owner FK — OwnedQuerySetMixin)

★ OwnedQuerySetMixin은 Inquiry 전용. 나머지 공유 테이블에는 적용 금지.
★ 정직성 레드라인 (dev/14): "심의완료/안전" 배지 금지, AI면책 고정.
"""
import hashlib
import hmac
import json

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.dateparse import parse_datetime
from django.utils.timezone import is_aware, localtime


BLOG_REVIEW_CONTENT_FIELDS = (
    'title', 'body', 'excerpt', 'cover_image', 'cover_asset_path', 'category', 'tags',
    'seo_title', 'seo_description', 'is_noindex',
)


def valid_blog_legal_review(value):
    """Return whether a legal-review record is complete enough to publish."""
    required = {'reviewer', 'credential', 'reviewed_at', 'reference'}
    if type(value) is not dict or set(value) != required:
        return False
    if any(
        type(value.get(key)) is not str or not value[key].strip()
        for key in ('reviewer', 'credential', 'reviewed_at', 'reference')
    ):
        return False
    if (
        len(value['reviewer'].strip()) > 100
        or len(value['credential'].strip()) > 100
        or len(value['reference'].strip()) > 200
    ):
        return False
    try:
        reviewed_at = parse_datetime(value['reviewed_at'])
    except (TypeError, ValueError):
        return False
    return reviewed_at is not None and is_aware(reviewed_at)


def blog_review_content_digest(post):
    """Hash the exact public fields covered by one legal review record."""
    payload = {}
    for field in BLOG_REVIEW_CONTENT_FIELDS:
        value = getattr(post, field, '')
        if field == 'cover_image':
            value = getattr(value, 'name', value) or ''
        payload[field] = value
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'),
    ).encode('utf-8')
    return hashlib.sha256(canonical).hexdigest()


# ─── 1. Post (공유) ────────────────────────────────────────────────────

class Post(models.Model):
    """게시판 글 — 공유 (인증 설계사 전원 읽기, 작성자/관리자 수정·삭제).

    소프트 삭제(is_deleted) vs 숨김(is_hidden) 분리:
      is_deleted=True : 본인 삭제 → 피드 제거, 댓글 있으면 "삭제된 게시글" 표기.
      is_hidden=True  : 관리자 모더레이션 → 피드 차단, 관리자 패널에서만 보임.
    """
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='posts',
        verbose_name='작성자',
    )
    title = models.CharField('제목', max_length=200, blank=True, default='')
    body = models.TextField('본문')
    is_hidden = models.BooleanField('관리자 숨김', default=False)
    is_deleted = models.BooleanField('소프트 삭제', default=False)
    view_count = models.PositiveIntegerField('조회수', default=0)
    like_count = models.PositiveIntegerField('좋아요 수(캐시)', default=0)
    comment_count = models.PositiveIntegerField('댓글 수(캐시)', default=0)
    pinned = models.BooleanField('상단 고정', default=False)
    category = models.CharField('카테고리', max_length=30, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'board_post'
        verbose_name = '게시글'
        verbose_name_plural = '게시글'
        ordering = ['-pinned', '-created_at']
        indexes = [
            models.Index(fields=['-created_at']),
            models.Index(fields=['category', '-created_at']),
            models.Index(fields=['is_deleted', 'is_hidden', '-created_at']),
        ]

    def __str__(self):
        return f'Post({self.id}) {self.title or "(제목 없음)"}'


# ─── 2. Comment (공유) ─────────────────────────────────────────────────

class Comment(models.Model):
    """댓글 — 공유 (대댓글 1단계까지만 허용).

    parent == None  → 최상위 댓글
    parent != None  → 1단계 대댓글 (parent.parent != None 이면 API 400 거부)
    """
    post = models.ForeignKey(
        Post,
        on_delete=models.CASCADE,
        related_name='comments',
        verbose_name='게시글',
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='comments',
        verbose_name='작성자',
    )
    parent = models.ForeignKey(
        'self',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='replies',
        verbose_name='부모 댓글 (대댓글용)',
    )
    body = models.TextField('내용')
    is_hidden = models.BooleanField('관리자 숨김', default=False)
    is_deleted = models.BooleanField('소프트 삭제', default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'board_comment'
        verbose_name = '댓글'
        verbose_name_plural = '댓글'
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['post', 'created_at']),
        ]

    def __str__(self):
        return f'Comment({self.id}) on Post({self.post_id})'


# ─── 3. PostLike (공유) ────────────────────────────────────────────────

class PostLike(models.Model):
    """좋아요 — unique_together(post, user)로 중복 DB 레벨 차단."""
    post = models.ForeignKey(
        Post,
        on_delete=models.CASCADE,
        related_name='likes',
        verbose_name='게시글',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='post_likes',
        verbose_name='설계사',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'board_post_like'
        verbose_name = '게시글 좋아요'
        verbose_name_plural = '게시글 좋아요'
        constraints = [
            models.UniqueConstraint(fields=['post', 'user'], name='uniq_post_like_post_user'),
        ]

    def __str__(self):
        return f'Like post={self.post_id} user={self.user_id}'


# ─── 4. PostAttachment (공유) ──────────────────────────────────────────

ALLOWED_MIME_TYPES = [
    'image/jpeg',
    'image/png',
    'image/webp',
    'application/pdf',
]

class PostAttachment(models.Model):
    """첨부 파일/이미지 — S3 presigned 업로드 완료 후 URL만 저장."""
    post = models.ForeignKey(
        Post,
        on_delete=models.CASCADE,
        related_name='attachments',
        verbose_name='게시글',
    )
    uploader = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='post_attachments',
        verbose_name='업로드 설계사',
    )
    file_url = models.CharField('파일 URL (S3/CDN)', max_length=500)
    file_name = models.CharField('원본 파일명', max_length=255)
    file_size = models.PositiveIntegerField('파일 크기 (bytes)')
    mime_type = models.CharField('MIME 타입', max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'board_post_attachment'
        verbose_name = '게시글 첨부'
        verbose_name_plural = '게시글 첨부'
        ordering = ['created_at']

    def __str__(self):
        return f'Attachment({self.id}) {self.file_name}'


# ─── 5. Report (신고자 본인 + 관리자) ─────────────────────────────────

class Report(models.Model):
    """신고 — unique_together(reporter, content_type, object_id)로 중복 차단."""
    CONTENT_POST = 'post'
    CONTENT_COMMENT = 'comment'
    CONTENT_TYPE_CHOICES = [
        (CONTENT_POST, '게시글'),
        (CONTENT_COMMENT, '댓글'),
    ]

    REASON_SPAM = 'spam'
    REASON_HATE = 'hate'
    REASON_ADULT = 'adult'
    REASON_FAKE = 'fake'
    REASON_OTHER = 'other'
    REASON_CHOICES = [
        (REASON_SPAM, '스팸/광고'),
        (REASON_HATE, '혐오/차별'),
        (REASON_ADULT, '음란'),
        (REASON_FAKE, '허위정보'),
        (REASON_OTHER, '기타'),
    ]

    STATUS_PENDING = 'pending'
    STATUS_RESOLVED = 'resolved'
    STATUS_DISMISSED = 'dismissed'
    STATUS_CHOICES = [
        (STATUS_PENDING, '처리 대기'),
        (STATUS_RESOLVED, '처리 완료 (숨김)'),
        (STATUS_DISMISSED, '기각'),
    ]

    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='reports',
        verbose_name='신고자',
    )
    content_type = models.CharField('대상 유형', max_length=10, choices=CONTENT_TYPE_CHOICES)
    object_id = models.BigIntegerField('대상 ID')
    reason = models.CharField('신고 이유', max_length=30, choices=REASON_CHOICES)
    detail = models.TextField('상세 설명', null=True, blank=True)
    status = models.CharField('처리 상태', max_length=10, choices=STATUS_CHOICES, default=STATUS_PENDING)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='resolved_reports',
        verbose_name='처리 관리자',
    )
    resolved_at = models.DateTimeField('처리 시각', null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'board_report'
        verbose_name = '신고'
        verbose_name_plural = '신고'
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['reporter', 'content_type', 'object_id'],
                name='uniq_report_reporter_content',
            ),
        ]

    def __str__(self):
        return f'Report({self.id}) {self.content_type}/{self.object_id} [{self.status}]'


# ─── 6. Notice (공개읽기 + 관리자쓰기) ────────────────────────────────

class Notice(models.Model):
    """공지사항 — 비로그인 포함 공개 읽기, 관리자만 작성·수정·삭제."""
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='notices',
        verbose_name='관리자 작성자',
    )
    title = models.CharField('제목', max_length=200)
    body = models.TextField('본문')
    is_pinned = models.BooleanField('상단 고정', default=False)
    is_published = models.BooleanField('게시됨', default=True)
    published_at = models.DateTimeField('게시 시각', null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'board_notice'
        verbose_name = '공지사항'
        verbose_name_plural = '공지사항'
        ordering = ['-is_pinned', '-created_at']

    def __str__(self):
        return f'Notice({self.id}) {self.title}'


# ─── 7. Faq (공개읽기 + 관리자쓰기) ───────────────────────────────────

class Faq(models.Model):
    """FAQ — 비로그인 포함 공개 읽기, 관리자만 작성·수정·삭제."""
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='faqs',
        verbose_name='관리자 작성자',
    )
    category = models.CharField('카테고리', max_length=50)
    question = models.CharField('질문', max_length=300)
    answer = models.TextField('답변')
    order = models.PositiveSmallIntegerField('정렬 순서', default=0)
    is_published = models.BooleanField('게시됨', default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'board_faq'
        verbose_name = 'FAQ'
        verbose_name_plural = 'FAQ'
        ordering = ['category', 'order', 'created_at']

    def __str__(self):
        return f'Faq({self.id}) [{self.category}] {self.question[:50]}'


# ─── 8. Inquiry (비공개 — owner FK) ────────────────────────────────────

class Inquiry(models.Model):
    """1:1 문의 — 작성자(owner) + 관리자만 접근. OwnedQuerySetMixin 적용 대상."""
    CATEGORY_FEATURE = 'feature'
    CATEGORY_BILLING = 'billing'
    CATEGORY_BUG = 'bug'
    CATEGORY_OTHER = 'other'
    CATEGORY_FEEDBACK = 'feedback'
    CATEGORY_CHOICES = [
        (CATEGORY_FEATURE, '기능문의'),
        (CATEGORY_BILLING, '요금결제'),
        (CATEGORY_BUG, '버그신고'),
        (CATEGORY_OTHER, '기타'),
        (CATEGORY_FEEDBACK, '이용 의견'),
    ]

    STATUS_OPEN = 'open'
    STATUS_ANSWERED = 'answered'
    STATUS_CLOSED = 'closed'
    STATUS_CHOICES = [
        (STATUS_OPEN, '답변 대기'),
        (STATUS_ANSWERED, '답변 완료'),
        (STATUS_CLOSED, '종료'),
    ]

    # ★ null 허용: 랜딩 등 비로그인 피드백은 owner=None(익명). OwnedQuerySetMixin
    #   은 filter(owner=user) 라 null-owner 행은 설계사 목록에 절대 노출되지 않음.
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='inquiries',
        verbose_name='작성 설계사',
    )
    category = models.CharField('문의 유형', max_length=30, choices=CATEGORY_CHOICES)
    title = models.CharField('제목', max_length=200)
    body = models.TextField('내용')
    status = models.CharField('상태', max_length=10, choices=STATUS_CHOICES, default=STATUS_OPEN)
    # ── 피드백 위젯 확장 필드 ──
    #   rating: 이용 의견(feedback) 별점 1..5. 그 외 카테고리는 null.
    #   meta:   불편 신고(bug) 자동 첨부 {path, user_agent, viewport} — 어드민 전용 표시.
    #   contact_email: 익명 제출 시 답변받을 이메일(선택). 로그인 제출은 빈 값.
    rating = models.PositiveSmallIntegerField('별점(1~5)', null=True, blank=True)
    meta = models.JSONField('메타(화면 정보)', null=True, blank=True, default=None)
    contact_email = models.EmailField('답변 이메일(익명)', blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'board_inquiry'
        verbose_name = '1:1 문의'
        verbose_name_plural = '1:1 문의'
        ordering = ['-created_at']

    def __str__(self):
        return f'Inquiry({self.id}) [{self.get_status_display()}] {self.title}'


# ─── 9. InquiryReply (관리자 작성, 문의 소유자 읽기) ──────────────────

class InquiryReply(models.Model):
    """1:1 문의 답변 — 관리자 작성, 해당 문의 소유자만 읽기."""
    inquiry = models.ForeignKey(
        Inquiry,
        on_delete=models.CASCADE,
        related_name='replies',
        verbose_name='문의',
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='inquiry_replies',
        verbose_name='답변 관리자',
    )
    body = models.TextField('답변 내용')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'board_inquiry_reply'
        verbose_name = '문의 답변'
        verbose_name_plural = '문의 답변'
        ordering = ['created_at']

    def __str__(self):
        return f'InquiryReply({self.id}) for Inquiry({self.inquiry_id})'


# ─── 10. BlogPost (인파 노트 — 공개읽기 + 관리자쓰기) ──────────────────

class BlogPost(models.Model):
    """인파 노트(블로그) 글 — 비로그인 포함 공개 읽기, 관리자만 작성·수정·삭제.

    ★ GLOBAL/SHARED 콘텐츠 (Notice/Faq 동형). owner FK 없음 → OwnedQuerySetMixin
      절대 미적용. boards 공유 예외군에 합류.
    is_published=False = 임시저장(초안): 공개 목록/상세에서 제외, 관리자만 열람.
    """
    CATEGORY_SALES = 'sales'
    CATEGORY_COVERAGE = 'coverage'
    CATEGORY_SAFETY = 'safety'
    CATEGORY_STORY = 'story'
    CATEGORY_CHOICES = [
        (CATEGORY_SALES, '고객 늘리기'),
        (CATEGORY_COVERAGE, '보장분석'),
        (CATEGORY_SAFETY, '안심 가이드'),
        (CATEGORY_STORY, '설계사 이야기'),
    ]
    REVIEW_GATE_NONE = 'none'
    REVIEW_GATE_LEGAL = 'legal'
    REVIEW_GATE_CHOICES = [
        (REVIEW_GATE_NONE, '추가 검토 없음'),
        (REVIEW_GATE_LEGAL, '법률 검토'),
    ]
    RESERVED_SLUGS = frozenset({'resources'})

    title = models.CharField('제목', max_length=200)
    # allow_unicode=True → 한글 슬러그 허용. unique+db_index 로 slug 조회 최적화.
    slug = models.SlugField('슬러그', max_length=200, unique=True, allow_unicode=True)
    body = models.TextField('본문(마크다운)')
    excerpt = models.CharField('요약', max_length=300, blank=True, default='')
    cover_image = models.ImageField('커버 이미지', upload_to='blog/', null=True, blank=True)
    cover_asset_path = models.CharField(
        '공개 정적 커버 경로', max_length=300, blank=True, default='',
    )
    category = models.CharField(
        '카테고리', max_length=30, choices=CATEGORY_CHOICES, default=CATEGORY_SALES,
    )
    tags = models.CharField('태그(쉼표 구분)', max_length=200, blank=True, default='')
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='blog_posts',
        verbose_name='작성자',
    )
    is_published = models.BooleanField('게시됨', default=False)
    review_gate = models.CharField(
        '게시 전 검토', max_length=20, choices=REVIEW_GATE_CHOICES,
        default=REVIEW_GATE_NONE,
    )
    legal_review_required = models.BooleanField(
        '법률 검토 고정', default=False, editable=False,
    )
    legal_review = models.JSONField('법률 검토 기록', null=True, blank=True)
    legal_review_reviewer = models.CharField(
        '법률 검토자', max_length=100, blank=True, default='', editable=False,
    )
    legal_review_credential = models.CharField(
        '법률 검토 자격', max_length=100, blank=True, default='', editable=False,
    )
    legal_reviewed_at = models.DateTimeField(
        '법률 검토 시각', null=True, blank=True, editable=False,
    )
    legal_review_reference = models.CharField(
        '법률 검토 근거', max_length=200, blank=True, default='', editable=False,
    )
    legal_review_content_digest = models.CharField(
        '법률 검토 본문 해시', max_length=64, blank=True, default='', editable=False,
    )
    published_at = models.DateTimeField('게시 시각', null=True, blank=True)
    seo_title = models.CharField('SEO 제목', max_length=60, blank=True, default='')
    seo_description = models.CharField('SEO 설명', max_length=160, blank=True, default='')
    is_noindex = models.BooleanField('검색 제외(noindex)', default=False)
    view_count = models.PositiveIntegerField('조회수', default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'board_blog_post'
        verbose_name = '인파 노트 글'
        verbose_name_plural = '인파 노트 글'
        ordering = ['-published_at', '-created_at']
        indexes = [
            models.Index(fields=['is_published', '-published_at']),
            models.Index(fields=['category', 'is_published']),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(is_published=False)
                    | (
                        models.Q(legal_review_required=False)
                        & ~models.Q(review_gate='legal')
                    )
                    | (
                        ~models.Q(legal_review_reviewer='')
                        & ~models.Q(legal_review_credential='')
                        & models.Q(legal_reviewed_at__isnull=False)
                        & ~models.Q(legal_review_reference='')
                        & ~models.Q(legal_review_content_digest='')
                    )
                ),
                name='blog_legal_review_required_to_publish',
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(legal_review_required=False)
                    | models.Q(review_gate='legal')
                ),
                name='blog_required_review_gate_locked',
            ),
        ]

    def __str__(self):
        return f'BlogPost({self.id}) {self.title}'

    def typed_legal_review(self):
        values = (
            self.legal_review_reviewer,
            self.legal_review_credential,
            self.legal_reviewed_at,
            self.legal_review_reference,
        )
        if not all(values):
            return None
        return {
            'reviewer': self.legal_review_reviewer,
            'credential': self.legal_review_credential,
            'reviewed_at': self.legal_reviewed_at.isoformat(),
            'reference': self.legal_review_reference,
        }

    def has_current_legal_review(self):
        review = self.legal_review
        if not valid_blog_legal_review(review):
            return False
        if (
            review['reviewer'].strip() != self.legal_review_reviewer
            or review['credential'].strip() != self.legal_review_credential
            or review['reference'].strip() != self.legal_review_reference
            or parse_datetime(review['reviewed_at']) != self.legal_reviewed_at
        ):
            return False
        return bool(
            self.typed_legal_review()
            and len(self.legal_review_content_digest) == 64
            and hmac.compare_digest(
                self.legal_review_content_digest,
                blog_review_content_digest(self),
            )
        )

    def public_legal_review(self):
        if not self.has_current_legal_review():
            return None
        return {
            'reviewer': self.legal_review_reviewer,
            'credential': self.legal_review_credential,
            'reviewed_on': localtime(self.legal_reviewed_at).date().isoformat(),
        }

    def _validate_publication_gate(self):
        if self.legal_review_required and self.review_gate != self.REVIEW_GATE_LEGAL:
            raise ValidationError({
                'review_gate': '이 글의 법률 검토 설정은 서버에서 고정되어 있어요.',
            })
        if self.legal_review is not None and not valid_blog_legal_review(self.legal_review):
            raise ValidationError({
                'legal_review': '법률 검토 기록의 담당자, 자격, 시각, 근거를 모두 입력해 주세요.',
            })
        if (
            self.is_published
            and (self.legal_review_required or self.review_gate == self.REVIEW_GATE_LEGAL)
            and not self.has_current_legal_review()
        ):
            raise ValidationError({
                'legal_review': '현재 글의 법률 검토 기록을 모두 입력하면 게시할 수 있어요.',
            })

    def _validate_slug_gate(self):
        if self.slug in self.RESERVED_SLUGS:
            raise ValidationError({
                'slug': '이 주소는 무료 자료 페이지에서 사용하고 있어요. 다른 주소를 입력해 주세요.',
            })

    def clean(self):
        super().clean()
        self._validate_slug_gate()
        self._validate_publication_gate()

    def save(self, *args, **kwargs):
        self._validate_slug_gate()
        self._validate_publication_gate()
        return super().save(*args, **kwargs)

    @classmethod
    def generate_unique_slug(cls, raw, exclude_pk=None):
        """제목/입력 슬러그에서 유니크 슬러그 생성 (한글 허용).

        충돌 시 -2, -3 ... 접미. 빈 값이면 'post' 폴백.
        """
        from django.utils.text import slugify
        # ★ SlugField(max_length=200) — 접미(-2/-3)까지 붙여도 200을 넘지 않게 base 를 190으로 컷.
        #   (긴 제목 2건이 같은 slug 로 충돌하면 base+'-2'=202자 → 프로드 Postgres 500. SQLite 는 못 잡음.)
        base = (slugify(raw or '', allow_unicode=True) or 'post')[:190]
        if base in cls.RESERVED_SLUGS:
            raise ValidationError({
                'slug': '이 주소는 무료 자료 페이지에서 사용하고 있어요. 다른 주소를 입력해 주세요.',
            })
        slug = base
        n = 2
        qs = cls.objects.all()
        if exclude_pk is not None:
            qs = qs.exclude(pk=exclude_pk)
        while qs.filter(slug=slug).exists():
            slug = f'{base}-{n}'
            n += 1
        return slug


class BlogContentRelease(models.Model):
    version = models.CharField(max_length=80, unique=True)
    digest = models.CharField(max_length=64)
    item_count = models.PositiveSmallIntegerField()
    before_snapshot = models.JSONField(null=True, blank=True, editable=False)
    after_snapshot = models.JSONField(null=True, blank=True, editable=False)
    applied_at = models.DateTimeField(auto_now_add=True)
    reverted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'board_blog_content_release'
        ordering = ['-applied_at']
