"""A particular implementation of a simulation variant. It is expected to be aware of the set of variables being
used, so the structures of Schema, Simulation, and the linear programming solver must be in agreement.

A rule of thumb. If an implementation relies on any presuppositions regarding variables being used (like using
hard-coded variable names), it should be implemented here.
"""

import pathlib
import random
import sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import sim
import linsmat
import functools
from dataclasses import dataclass, field
from sim import core
from generic import Log
import ut


@dataclass
class GeneratorOp(core.Op):

	def amount_planned(self):
		return self.sim_env.data_interface.get("x_eq", **self.op_identity.indices)

	def intensity(self):
		tl = self.sim_env.data_interface.get("tl", l=self.op_identity.indices.get("l"))
		amount = self.sim_env.data_interface.get(self.op_identity.var_amount_planned, **self.op_identity.indices)

		return amount / tl

	def on_tick_before(self):
		amount = self.intensity()
		self.op_state.output_container.amount = amount
		self.op_state.processed_container.amount += amount

	def register_processed(self):
		self.sim_env.data_interface.set(self.op_identity.var_amount_processed, self.op_state.processed_container.amount,
			**self.op_identity.indices)


class Simulation(core.SimEnv):

	@staticmethod
	def make_from_file(*args, **kwargs):
		env = core.SimEnv.make_from_file(*args, **kwargs)

		return Simulation(row_index=env.row_index, schema=env.schema, data_interface=env.data_interface)

	def _ops_all(self):
		generic_ops = list(self.ops.values())
		random.shuffle(generic_ops)
		return list(self.generator_ops.values()) + generic_ops + list(self.drop_ops.values())

	def __post_init__(self):
		sim.core.SimEnv.__post_init__(self)
		self.reset()

	def reset(self):
		self.__make_input_containers()
		self.__make_ops()
		self._trace = ut.Trace()  # Accumulated time series for each node

		assert self.schema.get_var_indices("tl") == ["l"]

	def __make_input_containers(self):
		self.input_containers = dict()  # {(j, rho): Container}

		for j, rho, l in self.schema.radix_map_iter("j", "rho", "l"):
			self.input_containers[(j, rho, l)] = sim.core.Container()

	def _input_container(self, j, rho, l):
		return self.input_containers[(j, rho, l)]

	def _transfer_op(self, j, i, rho, l):
		return self.transfer_ops[(j, i, rho, l)]

	def _is_connected(self, j, i, rho, l):
		"""
		Checks whether the planned network topology implies a channel between two nodes. If nothing is planned to be
		transfered between two nodes, or technical limitations imply no information flow between two nodes, the channel
		is considered absent.
		"""
		if j == i:
			Log.info(Simulation._is_connected, j, "and", i, "are not connected")
			return False

		psi = self.data_interface.get("psi", j=j, i=i, rho=rho, l=l)
		mm = self.data_interface.get("mm_psi", j=j, i=i, l=l)
		x = self.data_interface.get("x", j=j, i=i, rho=rho, l=l)
		m = self.data_interface.get("m_psi", j=j, i=i, rho=rho, l=l)

		res = psi > 0 and mm > 0 and x > 0 and m > 0

		if not res:
			Log.info(Simulation._is_connected, j, "and", i, "at", l, "are not connected")

		return res

	def l(self, now):
		sum = 0

		for l in range(self.schema.get_index_bound("l")):
			sum += self.data_interface.get("tl", l=l)

			if now < sum:
				return l

	def duration(self):
		return sum(map(lambda l: self.data_interface.get("tl", l=l), range(self.schema.get_index_bound("l"))))

	def op_check_l(self, op, l):
		"""
		Checks whether op belongs to the current stability timespan
		"""
		return op.op_identity.indices["l"] == l

	def trace(self):
		return self._trace.as_iter()

	def _t_iter(self):
		return ut.frange(0, self.duration(), self.dt())

	def run(self):

		#TODO integrate new Trace class

		prev_l = 0
		self._trace = ut.Trace()

		for t in self._t_iter():
			Log.debug(Simulation.run, "current time", t)
			l = self.l(t)
			ops = self._ops_all()

			# Trigger "tick_before"
			for op in ops:
				self._trace.add_point(t, op)  # Place a new tick in the history

				if prev_l != l:
					self._trace.add_l(t, op)
					Log.info("simulation", "new l", l, "at", t)

				if not self.op_check_l(op, l):
					continue

				if prev_l != l:
					if op.op_identity.var_amount_planned == "y":
						ind = op.op_identity.indices.copy()
						ind["l"] = l - 1
						# Keep the amount of processed info
						op.op_state.processed_container.amount = self.ops[self.schema.indices_dict_to_plain("y", **ind)].op_state.processed_container.amount

				op.on_tick_before()

			# Trigger "tick"
			for op in ops:
				if self.op_check_l(op, l):
					op.on_tick()

			# Trigger "tick_after"
			for op in ops:
				if self.op_check_l(op, l):
					op.on_tick_after()

			for op in ops:
				op.register_processed()

			prev_l = l

	def __make_ops(self):
		"""
		The following core is a generalized way to initialize a simulation. However, operations differ slightly,
		so there are conditional patches here and there.
		"""
		self.generator_ops = dict()
		self.ops = dict()
		self.drop_ops = dict()  # Because of the nature of the simulated process, drop ops are a sort of "tear-down" and should be triggered last

		for var_amount_planned, var_intensity, var_intensity_fraction, var_amount_processed, op_type in zip(
				["x", "y", "g", "z", "x_eq"],  # Ops will be identified using this set of variables
				["mm_psi", "mm_v", "mm_phi", "", "mm_x_eq"],  # TODO: Handle empty variables
				["m_psi", "m_v", "m_phi", "", ""],
				["x^", "y^", "g^", "z^", "x_eq^"],
				[sim.core.TransferOp, sim.core.StoreOp, sim.core.ProcessOp, sim.core.DropOp, GeneratorOp]):
			for indices in self.schema.radix_map_iter_var_dict(var_amount_planned):
				j, rho, l = [indices[1][ind] for ind in ["j", "rho", "l"]]

				if var_amount_planned == "x":
					i = indices[1]["i"]

					# Optimization to prevent exponential explosion
					if not self._is_connected(j=j, i=i, rho=rho, l=l):
						continue

				indices_plain = self.schema.indices_dict_to_plain(var_amount_planned, **indices[1])
				storage = self.ops

				if var_amount_planned == "z":
					storage = self.drop_ops
				elif var_amount_planned == "x_eq":
					storage = self.generator_ops

				storage[indices_plain] = op_type(
					sim_env=self,
					op_identity=sim.core.OpIdentity(
						indices=indices[1],
						var_amount_planned=var_amount_planned,
						var_intensity=var_intensity,
						var_intensity_fraction=var_intensity_fraction,
						var_amount_processed=var_amount_processed,
						indices_amount_planned=indices[1],
						indices_intensity=dict(filter(lambda d: d[0] != "rho", indices[1].items())),
						indices_intensity_fraction=indices[1],
						indices_amount_processed=indices[1]
					),
					op_state = sim.core.OpState(
						input_container=self._input_container(j=j, rho=rho, l=l),
						processed_container=sim.core.Container(),
					)
				)

				if var_amount_planned == "x_eq":
					# Initialize input containers with initial values
					storage[indices_plain].op_state.input_container.amount = self.data_interface.get("x_eq",
						**storage[indices_plain].op_identity.indices)
					storage[indices_plain].op_state.output_container = self._input_container(j=j, rho=rho, l=l)

				if var_amount_planned == "x":
					storage[indices_plain].op_state.output_container = self._input_container(j=indices[1]["i"], rho=rho,
						l=l)
