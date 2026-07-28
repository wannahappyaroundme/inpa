from django.urls import path

from .views import (
    CompleteUploadView,
    ClovaCallbackView,
    RecordingCapabilityView,
    RecordingDetailView,
    RecordingDownloadURLView,
    RecordingListView,
    RecordingPartURLView,
    RecordingPlayURLView,
    RecordingSourceDeleteView,
    RecordingSummarizeView,
    UploadSessionView,
)

app_name = 'consultations'

urlpatterns = [
    path(
        'consultations/clova-callback/<str:token>/',
        ClovaCallbackView.as_view(),
        name='clova-callback',
    ),
    path(
        'customers/<int:customer_pk>/recordings/',
        RecordingListView.as_view(),
        name='recording-list',
    ),
    path(
        'customers/<int:customer_pk>/recordings/capability/',
        RecordingCapabilityView.as_view(),
        name='recording-capability',
    ),
    path(
        'customers/<int:customer_pk>/recordings/upload-sessions/',
        UploadSessionView.as_view(),
        name='recording-upload-session',
    ),
    path(
        'customers/<int:customer_pk>/recordings/<uuid:recording_id>/',
        RecordingDetailView.as_view(),
        name='recording-detail',
    ),
    path(
        'customers/<int:customer_pk>/recordings/<uuid:recording_id>/summarize/',
        RecordingSummarizeView.as_view(),
        name='recording-summarize',
    ),
    path(
        'customers/<int:customer_pk>/recordings/<uuid:recording_id>/'
        'parts/<int:part_number>/',
        RecordingPartURLView.as_view(),
        name='recording-part-url',
    ),
    path(
        'customers/<int:customer_pk>/recordings/<uuid:recording_id>/'
        'complete-upload/',
        CompleteUploadView.as_view(),
        name='recording-complete-upload',
    ),
    path(
        'customers/<int:customer_pk>/recordings/<uuid:recording_id>/play-url/',
        RecordingPlayURLView.as_view(),
        name='recording-play-url',
    ),
    path(
        'customers/<int:customer_pk>/recordings/<uuid:recording_id>/'
        'download-url/',
        RecordingDownloadURLView.as_view(),
        name='recording-download-url',
    ),
    path(
        'customers/<int:customer_pk>/recordings/<uuid:recording_id>/source/',
        RecordingSourceDeleteView.as_view(),
        name='recording-source-delete',
    ),
]
