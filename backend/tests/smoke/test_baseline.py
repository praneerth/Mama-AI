import unittest


class TestMamaAIBaseline(unittest.TestCase):

    def test_configuration(self):
        from app.config import settings, logger

        self.assertEqual(settings.APP_NAME, "Mama AI")
        self.assertTrue(settings.APP_VERSION)
        self.assertEqual(logger.name, "mama_ai")

    def test_execution_bridge(self):
        from app.core.mama import run

        self.assertTrue(callable(run))

    def test_command_router(self):
        from app.commands.router import process_command

        self.assertTrue(callable(process_command))

    def test_api_application(self):
        from main import app

        self.assertIsNotNone(app)
        self.assertTrue(hasattr(app, "routes"))
        self.assertGreater(len(app.routes), 0)

    def test_gui_entrypoint(self):
        from app.gui.main_window import start_gui

        self.assertTrue(callable(start_gui))


if __name__ == "__main__":
    unittest.main()