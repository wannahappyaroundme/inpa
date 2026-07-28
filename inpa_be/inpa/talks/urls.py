from django.urls import path
from rest_framework.routers import SimpleRouter

from .views import PersonalTalkTemplateViewSet, TalkTemplatePreferenceView

app_name = 'talks'

router = SimpleRouter()
router.register(
    'talk-templates',
    PersonalTalkTemplateViewSet,
    basename='talk-template',
)

urlpatterns = [
    path(
        'talk-template-preferences/',
        TalkTemplatePreferenceView.as_view(),
        name='talk-template-preference',
    ),
    *router.urls,
]
