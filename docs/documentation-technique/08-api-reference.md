# 08 — API REST (référence générée depuis le code)

> Généré par `outils/generer_reference.py` depuis le résolveur d'URL Django.
> « Permissions » = `permission_classes` déclarées sur la vue ; certaines
> vues affinent l'accès dans `get_permissions()`, `get_queryset()` ou
> directement dans l'action (voir 09-authentification-permissions-securite.md).

**111 routes** (hors racines des routeurs DRF et admin Django).

## accounts

| Chemin | Méthode → action | Vue | Permissions | Serializer |
|---|---|---|---|---|
| `/api/auth/register/` | POST | `RegisterView` | AllowAny | RegisterSerializer |
| `/api/auth/login/` | POST | `LoginView` | AllowAny | LoginSerializer |
| `/api/auth/logout/` | POST | `LogoutView` | IsAuthenticated | — |
| `/api/auth/me/` | GET<br>PATCH | `ProfileView` | IsAuthenticated | — |
| `/api/auth/profile/` | GET<br>PATCH | `ProfileView` | IsAuthenticated | — |
| `/api/auth/profile/photo/` | POST | `ProfilePhotoView` | IsAuthenticated | — |

## adminpanel

| Chemin | Méthode → action | Vue | Permissions | Serializer |
|---|---|---|---|---|
| `/api/admin/dashboard/` | GET | `DashboardStatsView` | IsAuthenticated, IsAdminUserRole | — |
| `/api/admin/activite/` | GET | `ActiviteRecenteView` | IsAuthenticated, IsAdminUserRole | — |
| `/api/admin/utilisateurs/` | GET → list | `UserAdminViewSet` | IsAuthenticated, IsAdminUserRole | UserAdminSerializer |
| `/api/admin/utilisateurs/<pk>/` | GET → retrieve | `UserAdminViewSet` | IsAuthenticated, IsAdminUserRole | UserAdminSerializer |
| `/api/admin/utilisateurs/<pk>/statut/` | POST → changer_statut | `UserAdminViewSet` | IsAuthenticated, IsAdminUserRole | UserAdminSerializer |
| `/api/admin/clients/` | GET → list | `ClientAdminViewSet` | IsAuthenticated, IsAdminUserRole | ClientAdminSerializer |
| `/api/admin/clients/<pk>/` | GET → retrieve | `ClientAdminViewSet` | IsAuthenticated, IsAdminUserRole | ClientAdminSerializer |
| `/api/admin/prestataires/` | GET → list | `PrestataireAdminViewSet` | IsAuthenticated, IsAdminUserRole | PrestataireAdminSerializer |
| `/api/admin/prestataires/<pk>/` | GET → retrieve | `PrestataireAdminViewSet` | IsAuthenticated, IsAdminUserRole | PrestataireAdminSerializer |
| `/api/admin/prestataires/<pk>/score-confiance/` | GET → score_confiance | `PrestataireAdminViewSet` | IsAuthenticated, IsAdminUserRole | PrestataireAdminSerializer |
| `/api/admin/demandes/` | GET → list | `DemandeAdminViewSet` | IsAuthenticated, IsAdminUserRole | DemandeAdminSerializer |
| `/api/admin/demandes/<pk>/` | GET → retrieve | `DemandeAdminViewSet` | IsAuthenticated, IsAdminUserRole | DemandeAdminSerializer |
| `/api/admin/devis/` | GET → list | `DevisAdminViewSet` | IsAuthenticated, IsAdminUserRole | DevisAdminSerializer |
| `/api/admin/devis/<pk>/` | GET → retrieve | `DevisAdminViewSet` | IsAuthenticated, IsAdminUserRole | DevisAdminSerializer |
| `/api/admin/rendez-vous/` | GET → list | `RendezVousAdminViewSet` | IsAuthenticated, IsAdminUserRole | RendezVousAdminSerializer |
| `/api/admin/rendez-vous/<pk>/` | GET → retrieve | `RendezVousAdminViewSet` | IsAuthenticated, IsAdminUserRole | RendezVousAdminSerializer |
| `/api/admin/localisations/` | GET → list | `LocalisationAdminViewSet` | IsAuthenticated, IsAdminUserRole | LocalisationAdminSerializer |
| `/api/admin/localisations/<pk>/` | GET → retrieve | `LocalisationAdminViewSet` | IsAuthenticated, IsAdminUserRole | LocalisationAdminSerializer |

## devis

| Chemin | Méthode → action | Vue | Permissions | Serializer |
|---|---|---|---|---|
| `/api/demandes/` | GET → list<br>POST → create | `DemandeDevisViewSet` | IsAuthenticated | DemandeDevisSerializer |
| `/api/demandes/<pk>/` | GET → retrieve<br>PUT → update<br>PATCH → partial_update<br>DELETE → destroy | `DemandeDevisViewSet` | IsAuthenticated | DemandeDevisSerializer |
| `/api/reponses/` | GET → list<br>POST → create | `ReponseDevisViewSet` | IsAuthenticated | ReponseDevisSerializer |
| `/api/reponses/<pk>/` | GET → retrieve<br>PUT → update<br>PATCH → partial_update<br>DELETE → destroy | `ReponseDevisViewSet` | IsAuthenticated | ReponseDevisSerializer |
| `/api/reponses/<pk>/accepter/` | POST → accepter | `ReponseDevisViewSet` | IsAuthenticated | ReponseDevisSerializer |

## diagnosis

| Chemin | Méthode → action | Vue | Permissions | Serializer |
|---|---|---|---|---|
| `/api/diagnostic/` | POST | `DiagnosticView` | AllowAny | — |

## disputes

| Chemin | Méthode → action | Vue | Permissions | Serializer |
|---|---|---|---|---|
| `/api/litiges/preuves/<uuid:pk>/fichier/` | GET | `PreuveLitigeFichierView` | IsAuthenticated | — |
| `/api/litiges/` | GET → list<br>POST → create | `LitigeViewSet` | IsAuthenticated, IsLitigeParticipantOrAdmin | — |
| `/api/litiges/<pk>/` | GET → retrieve<br>PUT → update<br>PATCH → partial_update<br>DELETE → destroy | `LitigeViewSet` | IsAuthenticated, IsLitigeParticipantOrAdmin | — |
| `/api/litiges/<pk>/preuves/` | POST → ajouter_preuve | `LitigeViewSet` | IsAuthenticated, IsLitigeParticipantOrAdmin | — |
| `/api/litiges/<pk>/analyse/` | GET → analyse | `LitigeViewSet` | IsAuthenticated, IsLitigeParticipantOrAdmin | — |
| `/api/litiges/<pk>/confirmer-reprise/` | POST → confirmer_reprise | `LitigeViewSet` | IsAuthenticated, IsLitigeParticipantOrAdmin | — |
| `/api/litiges/<pk>/demander-reprise/` | POST → demander_reprise | `LitigeViewSet` | IsAuthenticated, IsLitigeParticipantOrAdmin | — |
| `/api/litiges/<pk>/prendre_en_charge/` | POST → prendre_en_charge | `LitigeViewSet` | IsAuthenticated, IsLitigeParticipantOrAdmin | — |
| `/api/litiges/<pk>/reattribuer/` | POST → reattribuer | `LitigeViewSet` | IsAuthenticated, IsLitigeParticipantOrAdmin | — |
| `/api/litiges/<pk>/rejeter/` | POST → rejeter | `LitigeViewSet` | IsAuthenticated, IsLitigeParticipantOrAdmin | — |
| `/api/litiges/<pk>/resoudre/` | POST → resoudre | `LitigeViewSet` | IsAuthenticated, IsLitigeParticipantOrAdmin | — |

## drf_spectacular

| Chemin | Méthode → action | Vue | Permissions | Serializer |
|---|---|---|---|---|
| `/api/schema/` | GET | `SpectacularAPIView` | AllowAny | — |
| `/api/docs/` | GET | `SpectacularSwaggerView` | AllowAny | — |

## locations

| Chemin | Méthode → action | Vue | Permissions | Serializer |
|---|---|---|---|---|
| `/api/location/` | GET → list<br>POST → create | `LocalisationViewSet` | IsAuthenticated | LocalisationSerializer |
| `/api/location/<pk>/` | GET → retrieve<br>PUT → update<br>PATCH → partial_update<br>DELETE → destroy | `LocalisationViewSet` | IsAuthenticated | LocalisationSerializer |

## messaging

| Chemin | Méthode → action | Vue | Permissions | Serializer |
|---|---|---|---|---|
| `/api/messages/` | GET → list<br>POST → create | `MessageViewSet` | IsAuthenticated | MessageSerializer |
| `/api/messages/<pk>/` | GET → retrieve | `MessageViewSet` | IsAuthenticated | MessageSerializer |

## notifications

| Chemin | Méthode → action | Vue | Permissions | Serializer |
|---|---|---|---|---|
| `/api/notifications/` | GET → list | `NotificationViewSet` | IsAuthenticated | NotificationSerializer |
| `/api/notifications/marquer-toutes-lues/` | POST → marquer_toutes_lues | `NotificationViewSet` | IsAuthenticated | NotificationSerializer |
| `/api/notifications/<pk>/` | GET → retrieve | `NotificationViewSet` | IsAuthenticated | NotificationSerializer |
| `/api/notifications/<pk>/marquer-lue/` | POST → marquer_lue | `NotificationViewSet` | IsAuthenticated | NotificationSerializer |

## prestations

| Chemin | Méthode → action | Vue | Permissions | Serializer |
|---|---|---|---|---|
| `/api/demande-prestation/` | GET → list<br>POST → create | `DemandePrestationViewSet` | IsAuthenticated | — |
| `/api/demande-prestation/<pk>/` | GET → retrieve<br>PUT → update<br>PATCH → partial_update<br>DELETE → destroy | `DemandePrestationViewSet` | IsAuthenticated | — |
| `/api/demande-prestation/<pk>/accepter/` | POST → accepter | `DemandePrestationViewSet` | IsAuthenticated | — |
| `/api/demande-prestation/<pk>/annuler/` | POST → annuler | `DemandePrestationViewSet` | IsAuthenticated | — |
| `/api/demande-prestation/<pk>/refuser/` | POST → refuser | `DemandePrestationViewSet` | IsAuthenticated | — |
| `/api/demande-prestation/<pk>/terminer/` | POST → terminer | `DemandePrestationViewSet` | IsAuthenticated | — |

## profiles

| Chemin | Méthode → action | Vue | Permissions | Serializer |
|---|---|---|---|---|
| `/api/prestataires/` | GET → list<br>POST → create | `PrestataireViewSet` | IsAuthenticated | — |
| `/api/prestataires/me/` | GET → me<br>PATCH → me | `PrestataireViewSet` | IsAuthenticated | — |
| `/api/prestataires/<pk>/` | GET → retrieve<br>PUT → update<br>PATCH → partial_update<br>DELETE → destroy | `PrestataireViewSet` | IsAuthenticated | — |
| `/api/profil/prestataire/` | GET → me<br>PATCH → me | `PrestataireViewSet` | IsAuthenticated | — |

## realtime

| Chemin | Méthode → action | Vue | Permissions | Serializer |
|---|---|---|---|---|
| `/api/ws/ticket/` | POST | `TicketWebSocketView` | IsAuthenticated | — |

## rendezvous

| Chemin | Méthode → action | Vue | Permissions | Serializer |
|---|---|---|---|---|
| `/api/disponibilites/` | GET → list<br>POST → create | `DisponibiliteViewSet` | IsDisponibiliteOwnerOrAdmin | DisponibiliteSerializer |
| `/api/disponibilites/<pk>/` | GET → retrieve<br>PUT → update<br>PATCH → partial_update<br>DELETE → destroy | `DisponibiliteViewSet` | IsDisponibiliteOwnerOrAdmin | DisponibiliteSerializer |
| `/api/rendez-vous/` | GET → list<br>POST → create | `RendezVousViewSet` | IsAuthenticated | — |
| `/api/rendez-vous/<pk>/` | GET → retrieve<br>PUT → update<br>PATCH → partial_update<br>DELETE → destroy | `RendezVousViewSet` | IsAuthenticated | — |
| `/api/rendez-vous/<pk>/annuler/` | POST → annuler | `RendezVousViewSet` | IsAuthenticated | — |
| `/api/rendez-vous/<pk>/confirmer/` | POST → confirmer | `RendezVousViewSet` | IsAuthenticated | — |
| `/api/rendez-vous/<pk>/refuser/` | POST → refuser | `RendezVousViewSet` | IsAuthenticated | — |
| `/api/rendez-vous/<pk>/terminer/` | POST → terminer | `RendezVousViewSet` | IsAuthenticated | — |
| `/api/prestataires/<uuid:prestataire_id>/disponibilites/` | GET | `DisponibilitesPubliquesView` | AllowAny | DisponibiliteSerializer |
| `/api/prestataires/<uuid:prestataire_id>/creneaux-disponibles/` | GET | `CreneauxDisponiblesView` | AllowAny | — |

## reports

| Chemin | Méthode → action | Vue | Permissions | Serializer |
|---|---|---|---|---|
| `/api/signalements/` | GET → list<br>POST → create | `SignalementViewSet` | IsAuthenticated, IsSignalementOwnerOrAdmin | — |
| `/api/signalements/<pk>/` | GET → retrieve<br>PUT → update<br>PATCH → partial_update<br>DELETE → destroy | `SignalementViewSet` | IsAuthenticated, IsSignalementOwnerOrAdmin | — |
| `/api/signalements/<pk>/prendre_en_charge/` | POST → prendre_en_charge | `SignalementViewSet` | IsAuthenticated, IsSignalementOwnerOrAdmin | — |
| `/api/signalements/<pk>/rejeter/` | POST → rejeter | `SignalementViewSet` | IsAuthenticated, IsSignalementOwnerOrAdmin | — |
| `/api/signalements/<pk>/traiter/` | POST → traiter | `SignalementViewSet` | IsAuthenticated, IsSignalementOwnerOrAdmin | — |

## rest_framework_simplejwt

| Chemin | Méthode → action | Vue | Permissions | Serializer |
|---|---|---|---|---|
| `/api/auth/token/refresh/` | POST | `TokenRefreshView` | — | — |

## reviews

| Chemin | Méthode → action | Vue | Permissions | Serializer |
|---|---|---|---|---|
| `/api/avis/` | GET → list<br>POST → create | `AvisViewSet` | IsAvisOwnerOrAdminOrPrestataireReadOnly | AvisSerializer |
| `/api/avis/<pk>/` | GET → retrieve<br>PUT → update<br>PATCH → partial_update<br>DELETE → destroy | `AvisViewSet` | IsAvisOwnerOrAdminOrPrestataireReadOnly | AvisSerializer |
| `/api/avis/<pk>/approuver/` | POST → approuver | `AvisViewSet` | IsAvisOwnerOrAdminOrPrestataireReadOnly | AvisSerializer |
| `/api/avis/<pk>/bloquer/` | POST → bloquer | `AvisViewSet` | IsAvisOwnerOrAdminOrPrestataireReadOnly | AvisSerializer |

## services

| Chemin | Méthode → action | Vue | Permissions | Serializer |
|---|---|---|---|---|
| `/api/categories/` | GET → list<br>POST → create | `CategorieViewSet` | IsAuthenticated | CategorieSerializer |
| `/api/categories/<pk>/` | GET → retrieve<br>PUT → update<br>PATCH → partial_update<br>DELETE → destroy | `CategorieViewSet` | IsAuthenticated | CategorieSerializer |
| `/api/services/` | GET → list<br>POST → create | `ServiceViewSet` | IsAuthenticated | ServiceSerializer |
| `/api/services/<pk>/` | GET → retrieve<br>PUT → update<br>PATCH → partial_update<br>DELETE → destroy | `ServiceViewSet` | IsAuthenticated | ServiceSerializer |
| `/api/services/<pk>/prestataires/` | GET → prestataires | `ServiceViewSet` | IsAuthenticated | ServiceSerializer |
| `/api/prestataire-services/` | GET → list<br>POST → create | `PrestataireServiceViewSet` | IsAuthenticated | PrestataireServiceSerializer |
| `/api/prestataire-services/<pk>/` | GET → retrieve<br>PUT → update<br>PATCH → partial_update<br>DELETE → destroy | `PrestataireServiceViewSet` | IsAuthenticated | PrestataireServiceSerializer |
| `/api/recherche/` | GET | `RechercheView` | AllowAny | RechercheResultatSerializer |
| `/api/recherche/intelligente/` | POST | `RechercheIntelligenteView` | AllowAny | — |

## verification

| Chemin | Méthode → action | Vue | Permissions | Serializer |
|---|---|---|---|---|
| `/api/verification/document/` | GET<br>POST | `MonDocumentIdentiteView` | IsAuthenticated, IsPrestataire | — |
| `/api/verification/documents/` | GET | `MesDocumentsIdentiteView` | IsAuthenticated, IsPrestataire | — |
| `/api/verification/document/<uuid:pk>/fichier/` | GET | `DocumentIdentiteFichierView` | IsAuthenticated | — |
| `/api/verification/admin/documents/` | GET → list | `DocumentIdentiteAdminViewSet` | IsAuthenticated, IsAdmin | DocumentIdentiteAdminSerializer |
| `/api/verification/admin/documents/<pk>/` | GET → retrieve | `DocumentIdentiteAdminViewSet` | IsAuthenticated, IsAdmin | DocumentIdentiteAdminSerializer |
| `/api/verification/admin/documents/<pk>/rejeter/` | POST → rejeter | `DocumentIdentiteAdminViewSet` | IsAuthenticated, IsAdmin | DocumentIdentiteAdminSerializer |
| `/api/verification/admin/documents/<pk>/valider/` | POST → valider | `DocumentIdentiteAdminViewSet` | IsAuthenticated, IsAdmin | DocumentIdentiteAdminSerializer |

## wallet

| Chemin | Méthode → action | Vue | Permissions | Serializer |
|---|---|---|---|---|
| `/api/wallet/mon-wallet/` | GET | `MonWalletView` | IsAuthenticated, IsPrestataire | — |
| `/api/wallet/mes-transactions/` | GET | `MesTransactionsView` | IsAuthenticated, IsPrestataire | — |
| `/api/wallet/mes-retraits/` | GET<br>POST | `MesRetraitsView` | IsAuthenticated, IsPrestataire | — |
| `/api/wallet/mes-paiements/` | GET<br>POST | `MesPaiementsView` | IsAuthenticated, IsClient | — |
| `/api/wallet/mes-paiements/<uuid:pk>/statut/` | GET | `StatutPaiementView` | IsAuthenticated, IsClient | — |
| `/api/wallet/webhooks/paydunya/` | POST | `PayDunyaCallbackView` | AllowAny | — |
| `/api/wallet/webhooks/paydunya-payout/` | POST | `PayDunyaPayoutCallbackView` | AllowAny | — |
| `/api/wallet/admin/paiements/` | GET → list | `PaymentAdminViewSet` | IsAuthenticated, IsAdmin | PaymentSerializer |
| `/api/wallet/admin/paiements/<pk>/` | GET → retrieve | `PaymentAdminViewSet` | IsAuthenticated, IsAdmin | PaymentSerializer |
| `/api/wallet/admin/retraits/` | GET → list | `WithdrawalAdminViewSet` | IsAuthenticated, IsAdmin | WithdrawalSerializer |
| `/api/wallet/admin/retraits/<pk>/` | GET → retrieve | `WithdrawalAdminViewSet` | IsAuthenticated, IsAdmin | WithdrawalSerializer |
| `/api/wallet/admin/transactions/` | GET → list | `TransactionAdminViewSet` | IsAuthenticated, IsAdmin | TransactionSerializer |
| `/api/wallet/admin/transactions/<pk>/` | GET → retrieve | `TransactionAdminViewSet` | IsAuthenticated, IsAdmin | TransactionSerializer |
