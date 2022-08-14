from tkinter import W
import linsmat
import argparse
from dataclasses import dataclass
import ut
import random


@dataclass
class RandomGenerator:
	"""
	Domain-aware random input generator. Generates constraints for the linear programming-based optimizer. Expects the
	provided schema to match the structure of data implied by the 2022 paper

	Generated sequences have the "k/v" format: (k, v)
	"""
	schema_filename: str
	variables: list
	var_bounds: dict

	def _functor_iter_wrapper(self):
		for var in self.variables:
			for prod in ut.radix_cartesian_product(self.schema.get_var_radix(var)):
				yield (var, *prod,), random.uniform(0, self.var_bounds[var])

	def __post_init__(self):
		self.schema = linsmat.Schema(None, self.schema_filename)
		self.iter_state = None

	def __iter__(self):
		self.iter_state = iter(self._functor_iter_wrapper())
		return self.iter_state

	def __next__(self):
		return next(self.iter_state)


def generate_random(schema, psi_upper, phi_upper, v_upper, x_eq_upper, output):
	generator = RandomGenerator(schema, ["psi", "v", "phi", "alpha_1", "x_eq"],
		{"psi": psi_upper, "phi": phi_upper, "v": v_upper, "alpha_1": 1.0, "x_eq": x_eq_upper})
	ut.file_create_if_not_exists(output)
	csv_data_provider = linsmat.PermissiveCsvBufferedDataProvider(output)

	for k, v in generator:
		csv_data_provider.set_plain(*k, v)

	csv_data_provider.sync()


def _parse_arguments():
	parser = argparse.ArgumentParser()
	parser.add_argument("--generate-random", action="store_true", help="Gen. random constraints for the linear programming task based on a schema")
	parser.add_argument("--schema", type=str, help="Schema JSON file")
	parser.add_argument("--psi-upper", type=float, help="Upper bound for psi (upper bound in a le-constraint)")
	parser.add_argument("--phi-upper", type=float, help="Upper bound for phi (upper bound in a le-constraint)")
	parser.add_argument("--v-upper", type=float, help="Upper bound for v (upper bound in a le-constraint)")
	parser.add_argument("--x-eq-upper", type=float, help="Upper bound for x_jlrho (right side in an eq-constraint)")
	parser.add_argument("--output", type=str, default=ut.Datetime.format_time(ut.Datetime.today()) + ".csv")

	return parser.parse_args()


def _main():
	args = _parse_arguments()

	if args.generate_random:
		generate_random(args.schema, args.psi_upper, args.phi_upper, args.v_upper, args.output)


if __name__ == "__main__":
	_main()
