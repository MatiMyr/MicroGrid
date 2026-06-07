import unittest

from domain.network_model import NetworkModel, Bus, SolarPanel
from app.network_service import NetworkService


class NetworkModelTest(unittest.TestCase):
    def test_add_solar_panel_and_remove_it(self):
        model = NetworkModel()
        model.add_bus(Bus(index=5, vn_kv=0.4, name="Nodo 5"))

        solar = model.add_solar_panel(SolarPanel(bus=5, p_mw=50.0, name="Panel 5"))

        self.assertEqual(len(model.net.sgen), 1)
        self.assertEqual(model.net.sgen.at[solar, "p_mw"], 50.0)

        model.remove_solar_panel(solar)
        self.assertEqual(len(model.net.sgen), 0)

    def test_service_applies_high_level_instruction(self):
        model = NetworkModel()
        model.add_bus(Bus(index=5, vn_kv=0.4, name="Nodo 5"))
        service = NetworkService(model)

        service.apply_instruction("agregar un panel solar de 50 kW en el nodo 5")

        self.assertEqual(len(model.net.sgen), 1)
        self.assertAlmostEqual(model.net.sgen.at[model.net.sgen.index[0], "p_mw"], 0.05)


if __name__ == "__main__":
    unittest.main()
