import unittest

from app.network_service import NetworkService
from app.simulation_service import SimulationService


class SimulationServiceTest(unittest.TestCase):
    def test_runpp_returns_result(self):
        service = SimulationService(NetworkService())
        result = service.run_pp()

        self.assertEqual(result.mode, "pp")
        self.assertGreaterEqual(result.total_losses_mw, 0.0)
        self.assertTrue(result.voltage_profile)
        self.assertTrue(result.line_loading_pct)

    def test_runopp_falls_back_to_power_flow(self):
        service = SimulationService(NetworkService())
        result = service.run_opp()

        self.assertIn(result.mode, {"opp", "pp"})
        self.assertGreaterEqual(result.autosufficiency_pct, 0.0)
        self.assertGreaterEqual(result.curtailment_solar_mw, 0.0)


if __name__ == "__main__":
    unittest.main()
