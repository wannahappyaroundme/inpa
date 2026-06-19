# 게시판 & 커뮤니티 (Boards & Community)

> 인파(Inpa) 개발 정본 · `docs/dev/17-boards-and-community.md` · 2026-06-19
> 범위: 게시판(SNS형 피드) · 공지사항 · FAQ · 1:1 문의 — 네 가지 공개/비공개 채널의 데이터 모델·화면 스펙·API·권한 계약.
> 정본 교차검증: `dev/02`(데이터모델·멀티테넌시) · `dev/09`(컴플라이언스) · `dev/14`(정직성 카피 규칙) · `dev/11`(인증·이메일/PW 전용).
> ★ 인증은 **이메일/비밀번호 전용** — 카카오 OAuth 전면 제거 확정.

---

## 0. 이 문서가 다루는 것 / 안 하는 것

| 다룸 | 안 다룸 |
|---|---|
| 게시판(Post/Comment/Like) 데이터모델·피드·상세·작성 화면 | 고객 데이터·보험 분석 화면 (dev/08·12) |
| 공지사항(Notice) 모델·목록·상세 | 설계사 KPI 대시보드 (dev/15) |
| FAQ 모델·목록·상세 | 메시지/카톡 발송 (dev/13) |
| 1:1 문의(Inquiry) 모델·작성·관리자 답변 | planner_baseline 기준선 (dev/10) |
| 신고(Report) 흐름·모더레이션 | 증권 OCR·담보분석 (dev/12) |
| 첨부 파일·이미지 업로드 | 이메일 발송 인프라 세부 (ops 영역) |
| 권한·가시성 매트릭스 완전 명세 | 외부 SNS 연동 (범위 밖) |

**네 채널 한 줄 정의**

| 채널 | 성격 | 쓰기 권한 | 읽기 권한 |
|---|---|---|---|
| **게시판** | SNS형 피드 — 인파 설계사 커뮤니티 | 인증 설계사 전원 | 인증 설계사 전원 |
| **공지사항** | 운영 공지 | 관리자만 | 전원(인증 불필요 허용 가능, 기본은 인증) |
| **FAQ** | 자주 묻는 질문 | 관리자만 | 전원 |
| **1:1 문의** | 비공개 고객지원 | 인증 설계사(본인 작성) | 작성자 본인 + 관리자 |

---

## 1. 가시성 매트릭스 (★ 가장 중요 — 모든 모델·API·화면에 일관 적용)

아래 매트릭스는 태스크 지시서의 "데이터 가시성/멀티테넌시 매트릭스"를 게시판 스트림에 적용한 것이다. 구현 전에 반드시 확인하고, 코드리뷰에서 일탈을 즉시 지적한다.

| 엔티티 | owner FK | 설계사 본인 | 다른 설계사 | 관리자 | 비로그인 |
|---|---|---|---|---|---|
| `Post` (게시판 글) | 없음(공유) | 읽기·쓰기·자기글 수정/삭제 | 읽기·좋아요·댓글 | 읽기·수정·삭제·숨김 | ❌ |
| `Comment` (댓글) | 없음(공유) | 읽기·작성·자기 댓글 수정/삭제 | 읽기·작성 | 읽기·삭제·숨김 | ❌ |
| `PostLike` (좋아요) | 없음(공유) | 본인 좋아요 생성/취소 | 읽기(카운트) | 읽기 | ❌ |
| `Report` (신고) | 없음 | 본인 신고 조회 | ❌ | 전체 조회·처리 | ❌ |
| `PostAttachment` (첨부) | 없음(공유) | 자기 글 첨부 업로드 | 읽기 | 읽기·삭제 | ❌ |
| `Notice` (공지) | 없음(공유) | 읽기 | 읽기 | 읽기·쓰기·수정·삭제 | 읽기(허용 가능) |
| `Faq` (FAQ) | 없음(공유) | 읽기 | 읽기 | 읽기·쓰기·수정·삭제 | 읽기(허용 가능) |
| `Inquiry` (1:1 문의) | **본인 FK** | 본인만 읽기·작성 | ❌ | 전체 읽기·답변 | ❌ |
| `InquiryReply` (답변) | — | 본인 문의의 답변만 읽기 | ❌ | 작성·수정·삭제 | ❌ |

**핵심 원칙**

- 게시판·공지·FAQ는 `owner FK 없음` — 공유(shared) 테이블이다. `OwnedQuerySetMixin`을 적용하지 않는다.
- 1:1 문의만 `Inquiry.owner = request.user`이고 `IsOwner` + `OwnedQuerySetMixin`을 적용한다.
- 공유 테이블의 수정·삭제는 `IsAuthorOrAdmin` — `obj.author == request.user or is_admin`.
- 신고 처리는 관리자 전용. 신고 접수는 인증 설계사 전원.

---

## 2. 데이터 모델

### 2.1 모델 관계도 (ASCII)

```
User(설계사)
  │
  ├─ Post ──< Comment
  │    │          │
  │    ├─< PostLike    (공유, owner FK 없음)
  │    ├─< PostAttachment
  │    └─< Report  ←─ (신고자: User FK)
  │
  └─ Inquiry ──< InquiryReply  (비공개, Inquiry.owner = 설계사)

[관리자 작성]
  Notice   (공유, owner 없음)
  Faq      (공유, owner 없음, 카테고리 분류)
```

### 2.2 `Post` — 게시판 글

```
Post
  id               BigAutoField PK
  author           FK(User, SET_NULL, null=True)  # 탈퇴 시 "탈퇴한 사용자"
  title            CharField(200)                 # 선택 (피드형은 빈 제목 허용)
  body             TextField
  is_hidden        BooleanField(default=False)     # 관리자 숨김 처리 (삭제 ≠ 숨김)
  is_deleted       BooleanField(default=False)     # 소프트 삭제 (본인 삭제)
  view_count       PositiveIntegerField(default=0) # 조회수 (atomic increment)
  like_count       PositiveIntegerField(default=0) # 캐시 카운터 (PostLike 합산)
  comment_count    PositiveIntegerField(default=0) # 캐시 카운터
  created_at       DateTimeField(auto_now_add=True)
  updated_at       DateTimeField(auto_now=True)
  pinned           BooleanField(default=False)     # 관리자가 상단 고정
  category         CharField(30, null=True)        # 해시태그 or 선택 카테고리 (추정)
```

> **소프트 삭제 vs 숨김 분리**
> - `is_deleted=True`: 본인이 삭제. 피드에서 제거. 댓글 있으면 "삭제된 게시글입니다" 표기.
> - `is_hidden=True`: 관리자 모더레이션. 피드 노출 차단, 관리자 패널엔 보임.
> - 두 상태가 겹칠 수 있음 (삭제 후 신고 → 숨김). 쿼리 필터: `.filter(is_deleted=False, is_hidden=False)`.

### 2.3 `Comment` — 댓글

```
Comment
  id               BigAutoField PK
  post             FK(Post, CASCADE)
  author           FK(User, SET_NULL, null=True)
  parent           FK('self', null=True, CASCADE)  # 대댓글(1단계까지)
  body             TextField
  is_hidden        BooleanField(default=False)
  is_deleted       BooleanField(default=False)
  created_at       DateTimeField(auto_now_add=True)
  updated_at       DateTimeField(auto_now=True)
```

> 대댓글은 1단계(parent→child)만 허용. 2단계 이상 금지 — depth 무한 확장은 UX 혼란.
> 삭제된 댓글에 자식 댓글이 있으면 "삭제된 댓글입니다" 표기(본문 비움, 작성자 숨김).

### 2.4 `PostLike` — 좋아요

```
PostLike
  post             FK(Post, CASCADE)
  user             FK(User, CASCADE)
  created_at       DateTimeField(auto_now_add=True)
  Meta: unique_together(post, user)      # 중복 좋아요 DB 레벨 차단
```

> `Post.like_count`는 `PostLike.objects.filter(post=post).count()`를 캐싱한 값.
> 토글 API(`POST /likes/` → 없으면 생성·`Post.like_count +1`, 있으면 삭제·`-1`). 원자적 업데이트 필수(`F() expression` 사용).

### 2.5 `PostAttachment` — 첨부 파일/이미지

```
PostAttachment
  post             FK(Post, CASCADE)
  uploader         FK(User, SET_NULL, null=True)
  file_url         CharField(500)       # S3 presigned key 또는 CDN URL
  file_name        CharField(255)       # 원본 파일명
  file_size        PositiveIntegerField # bytes
  mime_type        CharField(100)       # image/jpeg, application/pdf 등
  created_at       DateTimeField(auto_now_add=True)
```

> 허용 MIME: `image/jpeg`, `image/png`, `image/webp`, `application/pdf`. 파일 크기 상한: 이미지 10MB / PDF 20MB (추정 — 운영 정책 확정 후 조정).
> S3 presigned URL로 FE에서 직접 업로드. BE는 완료 후 `file_url`만 저장.

### 2.6 `Report` — 신고

```
Report
  id               BigAutoField PK
  reporter         FK(User, SET_NULL, null=True)
  content_type     CharField(10)       # 'post' | 'comment'
  object_id        BigIntegerField     # Post.id 또는 Comment.id
  reason           CharField(30)       # spam | hate | adult | fake | other
  detail           TextField(null=True)
  status           CharField(10, default='pending')  # pending | resolved | dismissed
  resolved_by      FK(User, null=True)  # 처리 관리자
  resolved_at      DateTimeField(null=True)
  created_at       DateTimeField(auto_now_add=True)
```

> 같은 신고자가 같은 객체를 중복 신고 차단: `unique_together(reporter, content_type, object_id)`.
> 신고 임계(예: 3건 이상 → 자동 숨김)는 운영 정책 — 기본값은 **자동 숨김 없음, 관리자 수동 처리**로 시작.

### 2.7 `Notice` — 공지사항

```
Notice
  id               BigAutoField PK
  author           FK(User, SET_NULL, null=True)  # 관리자 계정
  title            CharField(200)
  body             TextField
  is_pinned        BooleanField(default=False)    # 피드 최상단 고정
  is_published     BooleanField(default=True)     # 초안 보관 지원
  published_at     DateTimeField(null=True)       # 예약 발행(추정)
  created_at       DateTimeField(auto_now_add=True)
  updated_at       DateTimeField(auto_now=True)
```

### 2.8 `Faq` — 자주 묻는 질문

```
Faq
  id               BigAutoField PK
  author           FK(User, SET_NULL, null=True)  # 관리자
  category         CharField(50)                  # '요금제' | '기능' | '컴플라이언스' | '기타'
  question         CharField(300)
  answer           TextField
  order            PositiveSmallIntegerField(default=0)  # 카테고리 내 정렬
  is_published     BooleanField(default=True)
  created_at       DateTimeField(auto_now_add=True)
  updated_at       DateTimeField(auto_now=True)
```

### 2.9 `Inquiry` & `InquiryReply` — 1:1 문의 (비공개)

```
Inquiry
  id               BigAutoField PK
  owner            FK(User, CASCADE)          # 설계사 작성자 (OwnedQuerySetMixin 적용)
  category         CharField(30)             # '기능문의' | '요금결제' | '버그신고' | '기타'
  title            CharField(200)
  body             TextField
  status           CharField(10, default='open')  # open | answered | closed
  created_at       DateTimeField(auto_now_add=True)
  updated_at       DateTimeField(auto_now=True)

InquiryReply
  id               BigAutoField PK
  inquiry          FK(Inquiry, CASCADE)
  author           FK(User, SET_NULL, null=True)   # 관리자
  body             TextField
  created_at       DateTimeField(auto_now_add=True)
  updated_at       DateTimeField(auto_now=True)
```

> `Inquiry.owner`가 있는 유일한 모델. `OwnedQuerySetMixin` + `IsOwner` 적용.
> `InquiryReply`는 Inquiry에 cascade — Inquiry.owner로 간접 소유권 상속.
> 관리자는 `get_queryset()` admin bypass로 전체 조회.

---

## 3. 화면 IA — 게시판 동선

```
하단탭(설계사) [홈] [고객] [커뮤니티] [캘린더] [내정보]
                              │
                    ┌─────────┼──────────┐
                    ▼         ▼          ▼
              /board      /notice     /faq
            (피드)      (공지사항)   (FAQ)
                    │
              /board/new   ←  글쓰기 버튼(FAB or 상단 아이콘)
              /board/:id      게시글 상세
              /board/:id/edit 수정 (본인만)

          [내정보] > [고객지원] > /inquiry
                                 /inquiry/new
                                 /inquiry/:id
```

> 커뮤니티 탭은 **게시판(피드) 기본 착지** + 서브탭으로 공지/FAQ 접근.
> 1:1 문의는 [내정보] 하위 — 고객지원 성격이지 커뮤니티 성격이 아님.
> 관리자는 `/admin/` 패널을 통해 별도 접근 (인파 관리자 페이지, 별도 문서).

---

## 4. 화면 스펙 — 게시판(피드)

### 4.1 피드 목록 (`/board`)

**레이아웃**: 단일 컬럼 카드 피드. 모바일 퍼스트.

세로 순서:

| # | 영역 | 컴포넌트 | 내용 |
|---|---|---|---|
| 1 | 상단 바 | `BoardHeader` | "게시판" 타이틀 + 오른쪽 글쓰기 아이콘 |
| 2 | 상단 고정글 | `PinnedPostBanner` | `pinned=True` 글 최대 3개. 배경색 구분 |
| 3 | 카테고리 필터 | `CategoryChips` | 전체 / 카테고리별 (가로 스크롤) |
| 4 | 글 목록 | `PostCard` × N | 무한스크롤 (커서 기반 페이지네이션) |
| 5 | 빈 상태 | `EmptyFeed` | "아직 게시글이 없어요 — 첫 글을 써보세요" + 글쓰기 CTA |

**`PostCard` 구조**:
```
[저자 아바타] [저자 이름 · 작성 시각]      [⋮ 더보기 메뉴]
[제목 (있을 경우 1줄 클립)]
[본문 미리보기 — 최대 3줄, 긴 글은 "더보기"]
[첨부 이미지 썸네일 (있을 경우 — 최대 3장 격자)]
─────────────────────────────────────────────
[♡ 좋아요 N]  [💬 댓글 N]  [조회 N]
```

**더보기 메뉴 (`⋮`)**: 본인 글 — 수정·삭제. 남의 글 — 신고.

**페이지네이션**:
- 커서 기반 (`?cursor=<base64 encoded id>`) — 무한스크롤에 offset 대신 커서.
- 첫 로드: 최신 20개. 스크롤 끝 → 다음 20개 자동 로드.
- 정렬 기본값: 최신순(`-created_at`). 추후 인기순(like_count) 옵션 추가 가능.

**검색**: 상단 검색바 → `?q=<키워드>` → `body + title LIKE` 서버 검색. 실시간 검색 금지 (debounce 500ms 후 서버 요청).

### 4.2 게시글 상세 (`/board/:id`)

세로 순서:

| # | 영역 | 비고 |
|---|---|---|
| 1 | 뒤로가기 + 제목 | 상단 네비 |
| 2 | 저자 정보 + 작성 시각 | 탈퇴 시 "탈퇴한 사용자" |
| 3 | 본문 (마크다운 렌더 또는 plaintext) | XSS: DOMPurify 처리 필수 |
| 4 | 첨부 이미지/파일 목록 | 이미지 → 탭 뷰어. PDF → 다운로드 |
| 5 | 좋아요 버튼 + 카운트 | 토글. 본인 글도 가능(추정) |
| 6 | 댓글 목록 | 작성순. 대댓글 인덴트 1단 |
| 7 | 댓글 입력창 | 하단 고정 or 목록 아래 |

**삭제된 글**: `is_deleted=True` → 404 반환 OR "삭제된 게시글입니다" 플레이스홀더 (댓글이 있으면 후자).
**숨김 글**: `is_hidden=True` → 관리자만 볼 수 있음. 일반 설계사에게 404.

### 4.3 글쓰기/수정 (`/board/new`, `/board/:id/edit`)

| 필드 | 설명 |
|---|---|
| 제목 | 선택 입력 (피드형은 제목 없는 단문 허용) |
| 본문 | 필수. Textarea (줄바꿈 보존). 최대 5,000자 (추정) |
| 카테고리 | 선택. 드롭다운 또는 칩 선택 |
| 첨부 파일 | 이미지/PDF. 최대 5개 (추정) |

수정 진입 조건: `request.user == post.author AND is_deleted=False AND is_hidden=False`.
**수정 이력 표시**: `updated_at != created_at`이면 "수정됨" 표기 (선택 — 운영 정책).

### 4.4 ASCII 와이어프레임 (모바일)

```
┌─────────────────────────────┐
│ ← 게시판             [✎]    │ ← BoardHeader
├─────────────────────────────┤
│ 📌 [운영팀] 인파 서비스 점검  │ ← PinnedPostBanner
├─────────────────────────────┤
│ (전체)(꿀팁)(질문)(모집)       │ ← CategoryChips
├─────────────────────────────┤
│ ┌───────────────────────┐   │
│ │ 😊 김설계 · 2시간 전  ⋮ │   │ ← PostCard
│ │                       │   │
│ │ 이 담보 어떻게 설명하세요 │   │
│ │ 고객한테 암진단비 얘기   │   │
│ │ 할 때…               │   │
│ │                       │   │
│ │ ♡ 12  💬 3  조회 87  │   │
│ └───────────────────────┘   │
│ ┌───────────────────────┐   │
│ │ 👤 이보험 · 어제       ⋮ │   │
│ │                       │   │
│ │ GA 이직 경험 있으신 분? │   │
│ │ ♡ 5   💬 8  조회 210 │   │
│ └───────────────────────┘   │
│   (스크롤 → 자동 다음 로드)   │
└─────────────────────────────┘
```

---

## 5. 화면 스펙 — 공지사항 (`/notice`)

### 5.1 목록

- 카드형 목록. `is_pinned=True` 상단 고정.
- `is_published=False` (초안) — 관리자 패널에서만 보임.
- 비인증 접근 허용 여부: **기본은 인증 필요**. 추후 공개 마케팅 공지가 필요하면 `is_public` 필드 확장 (추정).

### 5.2 상세

- 본문 렌더: 마크다운 or richtext. XSS 처리 필수.
- 댓글·좋아요 없음 (공지는 단방향).
- 하단 "이전 공지 / 다음 공지" 내비게이션.

---

## 6. 화면 스펙 — FAQ (`/faq`)

### 6.1 목록/아코디언

- 카테고리별 그룹핑 + 아코디언 (질문 탭 → 답변 펼치기).
- 검색 가능 (`?q=`).
- `order` 필드로 카테고리 내 정렬 (관리자 페이지에서 drag-to-reorder, 추정).

---

## 7. 화면 스펙 — 1:1 문의 (`/inquiry`)

### 7.1 문의 목록 (본인만)

```
┌─────────────────────────────┐
│ ← 1:1 문의       [+ 새 문의]│
├─────────────────────────────┤
│ [기능문의] 히트맵 표시 오류   │
│ 2026-06-18 · 답변완료 🟢     │
├─────────────────────────────┤
│ [요금결제] 구독 취소 방법     │
│ 2026-06-15 · 답변대기 🟡     │
└─────────────────────────────┘
```

### 7.2 문의 상세

- 문의 본문 + 첨부 이미지.
- 답변 (InquiryReply) 순서대로. 관리자 답변은 "인파 운영팀" 표기.
- `status=open` → "답변 대기 중" 배너.
- `status=answered` → 최신 답변 강조.

### 7.3 새 문의 작성 (`/inquiry/new`)

| 필드 | 설명 |
|---|---|
| 카테고리 | 선택 (기능문의 / 요금결제 / 버그신고 / 기타) |
| 제목 | 필수, 최대 200자 |
| 내용 | 필수, 최대 3,000자 |
| 첨부 | 선택, 이미지 최대 3장 |

---

## 8. API 계약

> 인증: `Authorization: Token <token>`. 이메일/비밀번호 로그인 후 발급된 DRF Token.
> 공유 테이블(Post/Comment/Notice/Faq)은 `owner` 필터 없음. 1:1 문의만 `owner` 필터.

### 8.1 게시판

| Method | Path | Auth | 용도 |
|---|---|---|---|
| GET | `/api/v1/board/posts/` | Token | 피드 목록 (커서 페이지네이션, 검색/필터) |
| POST | `/api/v1/board/posts/` | Token | 글 작성 |
| GET | `/api/v1/board/posts/:id/` | Token | 글 상세 (조회수 +1) |
| PATCH | `/api/v1/board/posts/:id/` | Token (IsAuthorOrAdmin) | 글 수정 |
| DELETE | `/api/v1/board/posts/:id/` | Token (IsAuthorOrAdmin) | 소프트 삭제 (`is_deleted=True`) |
| POST | `/api/v1/board/posts/:id/like/` | Token | 좋아요 토글 (생성/취소) |
| GET | `/api/v1/board/posts/:id/comments/` | Token | 댓글 목록 |
| POST | `/api/v1/board/posts/:id/comments/` | Token | 댓글 작성 |
| PATCH | `/api/v1/board/comments/:id/` | Token (IsAuthorOrAdmin) | 댓글 수정 |
| DELETE | `/api/v1/board/comments/:id/` | Token (IsAuthorOrAdmin) | 댓글 소프트 삭제 |
| POST | `/api/v1/board/reports/` | Token | 신고 접수 (글·댓글) |
| POST | `/api/v1/board/posts/attachments/` | Token | 첨부 presigned URL 발급 |

**피드 목록 쿼리 파라미터**

```
GET /api/v1/board/posts/?cursor=<base64>&category=꿀팁&q=암진단비
```

| 파라미터 | 설명 | 기본값 |
|---|---|---|
| `cursor` | 다음 페이지 커서 | — (첫 페이지) |
| `page_size` | 페이지 크기 | 20 |
| `category` | 카테고리 필터 | — (전체) |
| `q` | 검색어 (title + body LIKE) | — |
| `ordering` | `latest` \| `popular` | `latest` |

**피드 목록 응답 구조 (요약)**

```json
{
  "next_cursor": "base64string",
  "results": [
    {
      "id": 1,
      "author": { "id": 42, "display_name": "김설계" },
      "title": "이 담보 어떻게 설명하세요",
      "body_preview": "고객한테 암진단비 얘기 할 때…",
      "like_count": 12,
      "comment_count": 3,
      "view_count": 87,
      "created_at": "2026-06-19T10:00:00Z",
      "is_pinned": false,
      "thumbnail_url": null
    }
  ]
}
```

**좋아요 토글 응답**

```json
{ "liked": true, "like_count": 13 }
```

### 8.2 공지사항

| Method | Path | Auth | 용도 |
|---|---|---|---|
| GET | `/api/v1/board/notices/` | Token (AllowAny 검토 가능) | 공지 목록 |
| GET | `/api/v1/board/notices/:id/` | Token | 공지 상세 |
| POST | `/api/v1/board/notices/` | Token (IsAdmin) | 공지 작성 |
| PATCH | `/api/v1/board/notices/:id/` | Token (IsAdmin) | 공지 수정 |
| DELETE | `/api/v1/board/notices/:id/` | Token (IsAdmin) | 공지 삭제 |

### 8.3 FAQ

| Method | Path | Auth | 용도 |
|---|---|---|---|
| GET | `/api/v1/board/faqs/` | Token (AllowAny 검토 가능) | FAQ 목록 (카테고리 그룹) |
| GET | `/api/v1/board/faqs/:id/` | Token | FAQ 상세 |
| POST | `/api/v1/board/faqs/` | Token (IsAdmin) | 항목 생성 |
| PATCH | `/api/v1/board/faqs/:id/` | Token (IsAdmin) | 항목 수정 |
| DELETE | `/api/v1/board/faqs/:id/` | Token (IsAdmin) | 항목 삭제 |

### 8.4 1:1 문의

| Method | Path | Auth | 용도 |
|---|---|---|---|
| GET | `/api/v1/board/inquiries/` | Token (IsOwner — 본인만) | 내 문의 목록 |
| POST | `/api/v1/board/inquiries/` | Token | 문의 작성 |
| GET | `/api/v1/board/inquiries/:id/` | Token (IsOwner) | 문의 상세 + 답변 |
| PATCH | `/api/v1/board/inquiries/:id/` | Token (IsOwner) | 문의 수정 (answered 전까지) |
| DELETE | `/api/v1/board/inquiries/:id/` | Token (IsOwner) | 문의 취소 (open만) |
| POST | `/api/v1/board/inquiries/:id/replies/` | Token (IsAdmin) | 관리자 답변 작성 |
| PATCH | `/api/v1/board/inquiry-replies/:id/` | Token (IsAdmin) | 관리자 답변 수정 |

---

## 9. 권한 클래스 (Django DRF)

게시판 고유 권한 클래스 2개를 신규 정의한다.

```python
# boards/permissions.py (계약, 구현 코드 아님)

class IsAuthorOrAdmin(BasePermission):
    """
    공유 테이블(Post/Comment) 수정·삭제 권한.
    - 본인 글/댓글: 허용
    - 관리자: 허용
    - 그 외: deny (403)
    주의: is_hidden=True 글은 관리자만 접근 가능하게 get_object 오버라이드 필요.
    """
    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return True
        return obj.author == request.user or request.user.profile.is_admin


class IsAdmin(BasePermission):
    """
    공지사항·FAQ 작성·수정·삭제 / 신고 처리 / 1:1 문의 답변 — 관리자 전용.
    """
    def has_permission(self, request, view):
        return bool(request.user and request.user.profile.is_admin)
```

**`Inquiry` 소유권**: `Inquiry` ViewSet은 `OwnedQuerySetMixin` 상속 + `IsOwner` permission. 이것이 가시성 매트릭스에서 "본인만" 행을 기술적으로 강제한다.

---

## 10. 신고 흐름 (Report)

```
[설계사] 글/댓글 ⋮ → "신고" 탭
    │
    ▼
신고 이유 선택 (스팸/혐오/음란/허위정보/기타)
    │
POST /api/v1/board/reports/
    │
    ▼
[BE] Report 저장 (status=pending)
    │
    ├── 신고 접수 완료 토스트 ("신고가 접수되었습니다")
    │
    └── [자동 임계 없음] → 관리자 패널에서 수동 검토
              │
         resolved → Post/Comment.is_hidden=True (숨김)
         dismissed → 신고 기각 (글 유지)
```

**신고자 보호**: 신고한 사실·신고자 정보는 신고 당사자에게 노출하지 않음.
**반복 신고 차단**: 같은 신고자가 같은 객체를 중복 신고 시 `unique_together` 위반 → 400 "이미 신고한 콘텐츠입니다".

---

## 11. 첨부 파일 업로드 흐름

```
[FE] 파일 선택
    │
POST /api/v1/board/posts/attachments/  { file_name, mime_type, file_size }
    │
[BE] 유효성 검사 → S3 presigned PUT URL 발급
    │
[FE] presigned URL로 S3 직접 업로드
    │
[FE] 업로드 완료 → POST /api/v1/board/posts/ body에 attachment_ids 포함
    │
[BE] PostAttachment 연결 → Post 저장
```

**보안 검사 항목**:
- 파일 크기 상한 검사 (BE presigned 단계에서 `Content-Length` 조건 걸기).
- MIME 타입 화이트리스트: `image/jpeg, image/png, image/webp, application/pdf` 외 거부.
- S3 버킷은 퍼블릭 읽기 금지 — CDN/presigned GET URL로만 서비스.

---

## 12. 컴플라이언스 & 정직성 레드라인

게시판은 설계사 간 자유 커뮤니티이므로 AI 분석과 직접 연결되지 않는다. 그러나 아래 레드라인은 전 화면에 공통 적용한다.

**정직성 레드라인 (dev/14 준용)**

- [ ] 게시판 본문에 보험 상품명·보험료 수치를 표시할 때 "AI 생성 콘텐츠"임을 사용자가 구분할 수 있는 맥락이 없으면 AI 배지 금지 (설계사 직접 작성 구분).
- [ ] 인파 운영팀의 공지·FAQ는 "심의완료" / "보장 확정" 표현 금지 — 법적 책임 사유.
- [ ] 공지사항에 "이 기능을 쓰면 보험료 N% 절감" 등의 효과 보증 카피 금지.

**개인정보**

- [ ] 게시판 본문에 고객 정보(이름·생년·병력)를 올리는 것은 개인정보보호법 위반. 글 작성 폼에 "고객 개인정보를 포함하지 마세요" 경고 문구 표기 (강제 차단 불가, 고지만).
- [ ] 신고 → 관리자 처리 흐름에서 개인정보 포함 글을 즉시 숨김 처리할 수 있는 관리자 도구 필수.

**광고 / 스팸**

- [ ] 게시판을 상업 광고(타사 상품 홍보, 유사 서비스 링크 등)로 쓰는 것은 운영 정책으로 금지. 신고 이유 "스팸/광고" 포함.

---

## 13. 수용 기준 (Definition of Done)

**게시판 (Post/Comment/Like)**
- [ ] 피드 목록 커서 페이지네이션 정상 동작 (20개 단위, 다음 cursor 포함).
- [ ] 좋아요 토글 — `PostLike unique_together` 중복 방지 + `like_count` 원자 업데이트.
- [ ] `is_deleted=True` 글은 피드 미노출 + 댓글 있으면 "삭제된 게시글입니다" 표기.
- [ ] `is_hidden=True` 글은 관리자만 접근 (일반 설계사 404).
- [ ] 본인 글/댓글 수정·삭제 가능, 남의 글/댓글 수정·삭제 403.
- [ ] 대댓글 2단계 이상 생성 시 API 거부 (parent.parent != null → 400).
- [ ] XSS: 본문 렌더 시 DOMPurify 적용 확인 (dangerouslySetInnerHTML 사용 시 필수).
- [ ] 첨부 파일 MIME 화이트리스트 외 거부 (400).

**공지사항 / FAQ**
- [ ] 관리자만 작성·수정·삭제 가능 (일반 설계사 403).
- [ ] `is_published=False` 초안은 관리자 패널에서만 노출.
- [ ] FAQ 카테고리 아코디언 정렬 `order` 필드 기반.

**1:1 문의**
- [ ] 본인 문의 목록·상세 조회 정상 동작.
- [ ] 타 설계사의 Inquiry 접근 시 404 (OwnedQuerySetMixin 동작 확인).
- [ ] 관리자는 전체 Inquiry 조회 가능 (admin bypass).
- [ ] 답변 작성 후 `Inquiry.status = 'answered'` 자동 업데이트.

**신고**
- [ ] 같은 신고자 중복 신고 400.
- [ ] 신고 접수 → 관리자 패널에서 resolved/dismissed 처리 동작.
- [ ] 신고 처리 결과(숨김 여부)가 피드에 즉시 반영.

---

## 14. 미해소 갭 (openGaps)

| # | 갭 | 영향 | 우선순위 |
|---|---|---|---|
| 1 | **게시판 카테고리 확정** — 꿀팁/질문/모집/정보공유 등 레이블 + 관리자 추가 가능 여부 | 필터 칩 UI, DB enum vs 자유 문자열 선택 | 개발 전 PM 결정 필요 |
| 2 | **공지사항·FAQ 비인증 공개 여부** — 마케팅 공개 공지가 필요하면 `is_public` 필드 확장, 아니면 인증 필수로 고정 | API allowance, robots.txt | PM 결정 필요 |
| 3 | **신고 자동 숨김 임계** — "신고 N건 이상 → 자동 숨김"이 필요한지 여부. 현재 기본값은 수동 처리 | 운영 부하 vs 자동화 | 베타 운영 후 실측 결정 |
| 4 | **게시글 수정 이력 표시** — `updated_at != created_at`이면 "수정됨" 표기 여부 | 신뢰도 vs UX 복잡도 | 기본 표기 권장, PM 확인 |
| 5 | **본인 글 좋아요 허용 여부** — 본인이 자기 글에 좋아요를 누를 수 있는지 | PostLike unique_together만으로는 차단 안 됨, 별도 검사 필요 | PM 결정 필요 |
| 6 | **익명 게시 옵션** — 설계사 커뮤니티 특성상 민감한 질문(GA 갈등 등)을 익명으로 올리고 싶은 수요 가능 | author 노출 분기, 관리자는 실제 작성자 조회 가능해야 함 | 추후 기능, 베타 미포함 |
| 7 | **알림 연동** — 댓글·좋아요 발생 시 작성자에게 인앱 알림. `Notification` 모델(dev/02) 확장 필요 | 알림 type 추가: `board_comment`, `board_like` | dev/02와 교차 설계 필요 |
| 8 | **첨부 파일 S3 버킷 / CDN 설정** — 게시판 첨부와 증권 OCR 파일이 같은 버킷을 쓸지 분리할지 | 접근 제어 정책, 비용 | ops 결정 필요 |
