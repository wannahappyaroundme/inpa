from django.urls import path

from .views import (
    CompleteUploadView,
    RecordingCapabilityView,
    RecordingDetailView,
    RecordingListView,
    RecordingPartURLView,
    RecordingPlayURLView,
    RecordingSourceDeleteView,
    UploadSessionView,
)

app_name = 'consultations'

urlpatterns = [
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
        'customers/<int:customer_pk>/recordings/<uuid:recording_id>/source/',
        RecordingSourceDeleteView.as_view(),
        name='recording-source-delete',
    ),
]

