"""admin_console 모델 — 신규 모델 최소화 (dev/19 §2.2).

admin_console 앱은 기존 모델 위에 관리 API를 얹는다.
Notice/Faq/Inquiry/InquiryReply/Report/PromotionOrder/PromotionOrderStatusLog 등은
inpa.boards, inpa.promotion 앱에 이미 정의됨 — 이 앱에서는 import만.
NormalizationDict/UnmatchedLog는 inpa.analysis 앱에 정의됨.
ConsentLog는 inpa.customers 앱에 정의됨.

★ 이 앱이 직접 소유하는 신규 모델은 없다.
  (모든 데이터 모델은 각 도메인 앱에 위치 — 중앙화 회피, foliio 패턴 일치.)
"""

# 이 파일은 의도적으로 비워둠.
# 도메인 모델은 해당 앱에서 import.
