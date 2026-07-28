from django.db import transaction
from rest_framework import status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from inpa.core.mixins import OwnedQuerySetMixin
from inpa.core.permissions import IsEmailVerified, IsOwner

from .models import PersonalTalkTemplate, TalkTemplatePreference
from .serializers import (
    PersonalTalkTemplateSerializer,
    TalkTemplatePreferenceSerializer,
)


class PersonalTalkTemplateViewSet(
    OwnedQuerySetMixin,
    viewsets.ModelViewSet,
):
    permission_classes = [IsAuthenticated, IsEmailVerified, IsOwner]
    serializer_class = PersonalTalkTemplateSerializer
    queryset = PersonalTalkTemplate.objects.all()

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .filter(is_deleted=False)
            .order_by('sort_order', 'created_at', 'id')
        )

    def list(self, request, *args, **kwargs):
        templates = self.get_serializer(self.get_queryset(), many=True).data
        hidden_source_keys = list(
            TalkTemplatePreference.objects.filter(
                owner=request.user,
                is_hidden=True,
            )
            .order_by('source_key')
            .values_list('source_key', flat=True)
        )
        return Response(
            {
                'results': templates,
                'hidden_source_keys': hidden_source_keys,
            }
        )

    def perform_destroy(self, instance):
        instance.is_deleted = True
        instance.save(update_fields=('is_deleted', 'updated_at'))


class TalkTemplatePreferenceView(APIView):
    permission_classes = [IsAuthenticated, IsEmailVerified]

    def put(self, request):
        serializer = TalkTemplatePreferenceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            preference, _ = TalkTemplatePreference.objects.update_or_create(
                owner=request.user,
                source_key=serializer.validated_data['source_key'],
                defaults={
                    'is_hidden': serializer.validated_data['is_hidden'],
                },
            )
        return Response(
            TalkTemplatePreferenceSerializer(preference).data,
            status=status.HTTP_200_OK,
        )
