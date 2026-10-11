from django.urls import path, re_path
from rest_framework.renderers import JSONOpenAPIRenderer
from rest_framework.schemas import get_schema_view

from . import pages
from .api import views as v

D = '<str:code>'
ID = '<uuid:pk>'

api = [
    path('org/', v.OrgView.as_view()),
    path('organizations/', v.OrganizationCreateView.as_view()),
    path('members/', v.MembersView.as_view()),
    path('role-policies/', v.RolePoliciesView.as_view()),
    path('prefs/<str:key>/', v.PrefsView.as_view()),
    path('search/', v.SearchView.as_view()),
    path('labels/', v.LabelsView.as_view()),
    path('files/', v.FileUploadView.as_view()),
    path('clients/check-duplicates/', v.ClientDuplicatesView.as_view()),
    # фото
    path('photos/reorder/', v.PhotosReorderView.as_view()),
    path(f'photos/{ID}/', v.PhotoDetailView.as_view()),
    path(f'photos/{ID}/<str:variant>', v.PhotoFileView.as_view()),
    # конструктор
    path('directories/', v.DirectoriesView.as_view()),
    path('structure-log/', v.StructureLogView.as_view()),
    path(f'directories/{D}/', v.DirectoryDetailView.as_view()),
    path(f'directories/{D}/restore/', v.DirectoryRestoreView.as_view()),
    path(f'directories/{D}/copy/', v.DirectoryCopyView.as_view()),
    path(f'directories/{D}/log/', v.StructureLogView.as_view()),
    path(f'directories/{D}/fields/', v.FieldsView.as_view()),
    path(f'directories/{D}/fields/reorder/', v.FieldsReorderView.as_view()),
    path(f'directories/{D}/fields/<uuid:fid>/', v.FieldDetailView.as_view()),
    path(f'directories/{D}/fields/<uuid:fid>/restore/', v.FieldRestoreView.as_view()),
    # импорт
    path('import/upload/', v.ImportUploadView.as_view()),
    path('import/jobs/', v.ImportJobsView.as_view()),
    path('import/photos-zip/', v.PhotoZipImportView.as_view()),
    path('import/profiles/<int:pk>/', v.ImportProfileDetailView.as_view()),
    path(f'import/{ID}/', v.ImportJobView.as_view()),
    path(f'import/{ID}/preview/', v.ImportPreviewView.as_view()),
    path(f'import/{ID}/run/', v.ImportRunView.as_view()),
    path(f'import/{ID}/errors-file/', v.ImportErrorFileView.as_view()),
    # справочники
    path(f'd/models/{ID}/add-items/', v.ModelAddItemsView.as_view()),
    path(f'd/{D}/', v.DictListView.as_view()),
    path(f'd/{D}/meta/', v.DictMetaView.as_view()),
    path(f'd/{D}/options/', v.DictOptionsView.as_view()),
    path(f'd/{D}/export/', v.DictExportView.as_view()),
    path(f'd/{D}/template/', v.DictTemplateView.as_view()),
    path(f'd/{D}/bulk/', v.DictBulkView.as_view()),
    path(f'd/{D}/{ID}/', v.DictDetailView.as_view()),
    path(f'd/{D}/{ID}/archive/', v.DictArchiveView.as_view()),
    path(f'd/{D}/{ID}/restore/', v.DictRestoreView.as_view()),
    path(f'd/{D}/{ID}/history/', v.DictHistoryView.as_view()),
    path(f'd/{D}/{ID}/photos/', v.PhotosView.as_view()),
]

schema_view = get_schema_view(
    title='Bride — API «Мастер-данные»', version='1.0',
    description='REST API модуля «Мастер-данные». Аутентификация: заголовок Authorization: Bearer <AccessToken> '
                '(выдаёт /api/login или /api/refresh). Организация: заголовок X-Organization (необязательно).',
    renderer_classes=[JSONOpenAPIRenderer], public=True,
    authentication_classes=[], permission_classes=[])

urlpatterns = [
    path('api/md/schema/', schema_view, name='md-openapi'),
    path('api/md/docs/', pages.api_docs),
    path('md', pages.app_page),
    path('md/', pages.app_page),
    re_path(r'^md-assets/(?P<path>.+)$', pages.asset),
] + [path('api/md/' + str(p.pattern), p.callback) for p in api]
