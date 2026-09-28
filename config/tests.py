from unittest import mock

from django.test import SimpleTestCase

from config.settings import env_bool, env_list


class EnvBoolTests(SimpleTestCase):
    """Vérifie que la conversion des variables d'environnement en booléen
    ne tombe pas dans le piège de bool("False") == True.
    """

    def test_valeur_absente_renvoie_le_defaut(self):
        with mock.patch.dict("os.environ", {}, clear=False):
            self.assertTrue(env_bool("VARIABLE_INEXISTANTE_XYZ", True))
            self.assertFalse(env_bool("VARIABLE_INEXISTANTE_XYZ", False))

    def test_chaine_false_renvoie_faux(self):
        with mock.patch.dict("os.environ", {"DEBUG": "False"}):
            self.assertFalse(env_bool("DEBUG", True))

    def test_chaine_false_minuscule_renvoie_faux(self):
        with mock.patch.dict("os.environ", {"DEBUG": "false"}):
            self.assertFalse(env_bool("DEBUG", True))

    def test_chaine_true_renvoie_vrai(self):
        with mock.patch.dict("os.environ", {"DEBUG": "True"}):
            self.assertTrue(env_bool("DEBUG", False))

    def test_espaces_autour_de_la_valeur_sont_ignores(self):
        with mock.patch.dict("os.environ", {"DEBUG": "  false  "}):
            self.assertFalse(env_bool("DEBUG", True))


class EnvListTests(SimpleTestCase):
    """Vérifie le découpage des variables d'environnement en liste
    (ALLOWED_HOSTS, CORS_ALLOWED_ORIGINS, CSRF_TRUSTED_ORIGINS).
    """

    def test_valeurs_separees_par_des_virgules(self):
        with mock.patch.dict("os.environ", {"ALLOWED_HOSTS": "localhost,127.0.0.1"}):
            self.assertEqual(
                env_list("ALLOWED_HOSTS"),
                ["localhost", "127.0.0.1"],
            )

    def test_espaces_autour_des_valeurs_sont_retires(self):
        with mock.patch.dict("os.environ", {"ALLOWED_HOSTS": " localhost , 127.0.0.1 "}):
            self.assertEqual(
                env_list("ALLOWED_HOSTS"),
                ["localhost", "127.0.0.1"],
            )

    def test_valeur_absente_utilise_le_defaut(self):
        with mock.patch.dict("os.environ", {}, clear=False):
            self.assertEqual(
                env_list("VARIABLE_INEXISTANTE_XYZ", "a,b"),
                ["a", "b"],
            )

    def test_valeur_vide_renvoie_une_liste_vide(self):
        with mock.patch.dict("os.environ", {"CSRF_TRUSTED_ORIGINS": ""}):
            self.assertEqual(env_list("CSRF_TRUSTED_ORIGINS"), [])
