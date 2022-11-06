"""
API glue.

Linear solver and simulation optimizer have to be "in agreement". I.e they have
to operate upon the same ontology and data.

This module contains entities that fullfill 2 purposes.
1. They glue relevant pairs of linear programming and simulation optimizers together,
2. Complete up the optimization algorithm, ensuring data flow between the
optimizers, and checking for stop conditions.
"""

import sim_opt
import linsmat
import linsolv_planner
from dataclasses import dataclass
import simulation

@dataclass
class VirtOpt:
	"""
	The '22 paper.
	- Minimize loss (z)
	- Maximize processing (g)
	"""

	CONF_STOP_N_ITERATIONS = 20
	schema_path: str  # Path to .json schema file
	storage_path: str  # Path to .csv storage file
	conf_stop_n_iterations = CONF_STOP_N_ITERATIONS

	def __post_init__(self):
		# Construct ETL entities
		self.schema = linsmat.Schema(filename=self.schema_path)
		self.csv_provider = linsmat.PermissiveCsvBufferedDataProvider(csv_file_name=self.storage_path)
		self.csv_data_interface = linsmat.ZeroingDataInterface(provider=self.csv_provider, schema=self.schema)
		self.ram_provider = linsmat.DictRamDataProvider()
		self.ram_data_interface = linsmat.ZeroingDataInterface(provider=self.ram_provider, schema=self.schema)
		self.ram_data_interface.update(self.csv_data_interface)  # Ensure consistency

	def run(self):
		env = linsmat.Env(row_index=None, schema=self.schema, data_interface=self.ram_data_interface)
		virt_helper = linsmat.VirtHelper(env=env)
		ls_planner = linsolv_planner.LinsolvPlanner(data_interface=self.ram_data_interface, schema=self.schema)
		ga_sim_virt_opt = sim_opt.GaSimVirtOpt(simulation_constructor=simulation.Simulation.from_dis,
		                                       virt_helper=virt_helper)

		for _ in range(self.conf_stop_n_iterations):
			ls_planner.solve()
			best_performer_config = ga_sim_virt_opt.run()
			self.ram_data_interface.update(best_performer_config())  # TODO XXX Make sure that the `ls_planner`'s instance gets updated as well

		self.csv_data_interface.update(self.ram_data_interface)  # Save into CSV
