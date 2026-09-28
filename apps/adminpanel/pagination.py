# On importe la pagination par numéro de page.
from rest_framework.pagination import PageNumberPagination


# Cette classe configure la pagination utilisée par toutes les listes du back-office admin.
class AdminPagination(PageNumberPagination):
    """Pagination commune aux listes du module d'administration."""

    # Le nombre de résultats par page, par défaut.
    page_size = 20
    # Le nom du paramètre permettant au client de changer la taille de page.
    page_size_query_param = "page_size"
    # Le nombre maximal de résultats qu'une page peut contenir.
    max_page_size = 100
