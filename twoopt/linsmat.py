"""
ETL.

This module is primarily dedicated to preparing input data for the scipy's `linprog`, while doing so in a generalized
fashion for the case of changes. It takes care of indices and structure descriptions, and its primary purpose is to
decouple data formatting from domain specificities as much as possible.
"""

from dataclasses import dataclass
import functools
import ut
import json
import re
import io
import os
import csv
import pathlib
from generic import Log
import copy

log = ut.Log(file=__file__, level=ut.Log.LEVEL_VERBOSE)


@dataclass
class RowIndex:
	"""
	In linear equation's matrices, variables are stored according to some configuration. For example, for a problem w/
	variables "x", "y", "z", a row could have the following structure:

	Xa0b0 Xa0b1 Xa1b0 Xa1b1 Ya0c0 ...

	This class is responsible for transforming human-readable indices into positions in the vector. Speaking in terms of
	positional numeral systems, the position can be represented as a tuple of mixed-radix numbers:

	(Xab, Yac)

	Essentially, this class transforms a mixed-radix number into decimal, while having subject area-specific API.
	"""
	indices: dict  # Format {"index1": RANGE, "index2": RANGE, ...}.
	variables: dict  # Format {"variable1": [indices], "variable 2": indices, ...}
	from_zero: bool = True

	@staticmethod
	def make_from_schema(schema, variables, from_zero=True):
		index_set = functools.reduce(lambda s, var: s.union(set(schema.get_var_indices(var))), variables, set())
		indices_map = {i: schema.get_index_bound(i) for i in index_set}
		variables_map = {var: schema.get_var_indices(var) for var in variables}
		row_index = RowIndex(indices=indices_map, variables=variables_map, from_zero=from_zero)

		return row_index

	def _check_precedence(self, var_a, var_b):
		"""
		Returns True, when var_a appears before var_b
		"""
		return list(self.variables.keys()).index(var_a) < list(self.variables.keys()).index(var_b)

	def _to_mixed_radix_number(self, var, **indices):

		return list(map(lambda index: indices[index], self.variables[var]))

	def _get_radix_map_length(self, variable):
		return len(self.radix_maps[variable])

	def get_row_len(self):
		"""
		Returns the length of the entire row
		"""
		mult = lambda a, b: a * b
		map_radix_maps = map(lambda v: self.radix_maps[v], self.variables.keys())
		map_radix_map_to_decimal = map(lambda m: functools.reduce(mult, m, 1), map_radix_maps)
		res = sum(map_radix_map_to_decimal)

		return res

	def get_pos(self, variable, **indices):
		"""
		Transform a mixed radix number representing the variable's position to decimal one
		"""
		if not self.from_zero:
			indices = dict(map(lambda kv: (kv[0], kv[1] - 1), indices.items()))

		assert variable in self.variables.keys()  # Check if variable exists
		assert set(indices.keys()) == set(self.variables[variable])  # Check that all indices are present
		assert all([0 <= indices[i] <= self.indices[i] for i in indices.keys()])

		radix_number = self._to_mixed_radix_number(variable, **indices)
		mult = lambda a, b: a * b

		map_var = lambda var: sum(map(lambda i: radix_number[i] * self.radix_mult_vectors[var][i],
			range(len(self.radix_maps[var])))) if var == variable else 0 if self._check_precedence(var, variable) else \
			functools.reduce(mult, self.radix_maps[var], 1)

		return sum(map(map_var, self.variables.keys()))

	__call__ = get_pos

	def __post_init__(self):
		"""
		Forms radix map and radix scalar multiplication vector for numerical transofmations into a non-mixed radix
		number

		Example:
		indices: {j: 2, rho: 3}
		variables {x: [j, rho], y: [j]}
		radix map for x: [2, 3]

		With this radix map, a mixed radix number [1, 2, 1] could be converted into a non-mixed through multiplication:

		[1, 2, 1] * radix_mult_vector
		"""
		self.radix_maps = dict(zip(self.variables.keys(), map(lambda variable: list(map(
			lambda index: self.indices[index], self.variables[variable])), self.variables.keys())))
		self.radix_mult_vectors = dict()

		for v in self.variables.keys():
			npos = len(self.radix_maps[v])
			self.radix_mult_vectors[v] = [1 for _ in range(npos)]

			if npos > 1:
				for i in reversed(range(npos - 1)):
					self.radix_mult_vectors[v][i] = self.radix_maps[v][i + 1] * self.radix_mult_vectors[v][i + 1]


def arr_set(arr, rowindex, val, var, **indices):
	pos = rowindex.get_pos(var, **indices)
	arr[pos] = val

	return arr


@dataclass
class Schema:
	"""
	Wrapper over a dictionary containing schema information: indices, variables, boundaries
	Format example:
	{
		"indexbound": {
			"j": 3,
			"i": 2,
			"m": 4
		},
		"variableindices": {
			"x": ["j", "i"],
			"y": ["i", "j", "m"],
			"z": ["i", "m"]
		}
	}

	Bounds are counted from 0 to N: [0; N)
	"""
	data: dict = None
	filename: str = None

	def __post_init__(self):
		if self.filename is not None:
			self.read(self.filename)

	def read(self, filename="schema.json"):
		with open(filename, 'r') as f:
			try:
				self.data = json.loads(f.read())
			except FileNotFoundError as e:
				Log.error(Schema, "got exception", e)
				self.data = {
					"indexbound": dict(),
					"variableindices": dict(),
				}

	def variables(self):
		return copy.deepcopy(list(self.data["variableindices"].keys()))

	def write(self, filename="schema.json"):
		assert self.data is not None
		with open(filename, 'w') as f:
			f.write(self.data)

	def set_index_bound(self, index, bound):
		assert self.data is not None
		self.data["indexbound"][index] = bound

	def get_index_bound(self, index):
		assert self.data is not None
		assert index in self.data["indexbound"]
		return self.data["indexbound"][index]

	def make_radix_map(self, *indices):
		"""
		Makes an array of upper bounds using the indices provided
		"""
		return list(self.get_index_bound(i) for i in indices)

	def get_max_dec_from_indices(self, *indices):
		"""
		Returns a maxiumum possible decimal number encoded by a radix map produces from the provided indices' upper
		bounds
		"""
		mult = lambda a, b: a * b

		return functools.reduce(mult, self.make_radix_map(*indices), 1)

	def set_var_indices(self, var, *indices):
		assert self.data is not None
		assert len(indices) > 0
		self.data["variableindices"][var] = list(indices)

	def get_var_indices(self, var):
		assert self.data is not None
		assert var in self.data["variableindices"]
		return self.data["variableindices"][var]

	def get_var_radix(self, var):
		"""
		A tuple of variable indices can be represented as a mixed-radix number. Returns base of that number
		"""
		assert var in self.data["variableindices"]

		return list(map(lambda i: self.data["indexbound"][i], self.data["variableindices"][var]))

	get_radix_map = get_var_radix

	def radix_map_iter(self, *indices):
		radix_map = self.make_radix_map(*indices)

		for ind in ut.radix_cartesian_product(radix_map):
			yield ind

	def radix_map_iter_dict(self, *indices):
		for ind in self.radix_map_iter(*indices):
			yield {k: v for k, v in zip(indices, ind)}

	def radix_map_iter_var(self, var):
		indices = self.get_var_indices(var)
		yield from self.radix_map_iter(*indices)

	def radix_map_iter_var_dict(self, var):
		for ind in self.radix_map_iter_var(var):
			yield self.indices_plain_to_dict(var, *ind)

	def indices_dict_to_plain(self, variable, **indices):
		"""
		[VARAIBLE, {"index1": INDEX1, "index2": INDEX2}] -> [VARIABLE, INDEX1, INDEX2]
		"""
		assert type(variable) is str
		assert set(self.data["variableindices"][variable]) == set(indices.keys())
		indices_plain = tuple(map(lambda i: indices[i], self.data["variableindices"][variable]))

		return (variable,) + indices_plain

	def indices_plain_to_dict(self, variable, *indices):
		"""
		[VARIABLE, INDEX1, INDEX2] -> [VARAIBLE, {"index1": INDEX1, "index2": INDEX2}]
		"""
		assert type(variable) is str
		check_type_int = lambda i: type(i) is int
		assert all(map(check_type_int, indices))
		assert len(indices) == len(self.data["variableindices"][variable])
		indices_dict = dict(zip(self.data["variableindices"][variable], indices))

		return (variable, indices_dict)


@dataclass
class PermissiveCsvBufferedDataProvider(dict):
	"""
	Represents data in the following format
	{
		(VARAIBLE1, INDEX1, INDEX2) : VALUE,
		(VARIABLE2, INDEX1) : VALUE,
	}

	Guarantees and ensures that VARIABLE has type `str`, indices have type `int`, and VALUE has type `float`
	"""
	csv_file_name: str
	line_to_kv: object = lambda l: (tuple([l[0]] + list(map(int, l[1:-1]))), float(l[-1]))

	def get_plain(self, *key):
		assert key in self.keys()
		return self[key]

	def set_plain(self, *args):
		"""
		Adds a sequence of format (VAR, INDEX1, INDEX2, ..., VALUE) into the dictionary
		"""
		assert len(args) >= 2
		k, v = self.line_to_kv(args)
		self[k] = v

	def _into_iter_plain(self):
		stitch = lambda kv: kv[0] + (kv[1],)

		return map(stitch, self.items())

	into_iter_plain = _into_iter_plain  # Reveal the method

	def __post_init__(self):
		"""
		Parses data from a CSV file containing sequences of the following format:
		VARIABLE   SPACE_OR_TAB   INDEX1   SPACE_OR_TAB   INDEX2   ...   SPACE_OR_TAB   VALUE

		Expects the values to be stored according to Repr. w/ use of " " space symbol as the separator
		"""
		assert os.path.exists(self.csv_file_name)

		try:
			with open(self.csv_file_name, 'r') as f:
				lines = f.readlines()
				data = ''.join(map(lambda l: re.sub(r'( |\t)+', ' ', l), lines))  # Sanitize, replace spaces or tabs w/ single spaces
				data = data.strip()
				reader = csv.reader(io.StringIO(data), delimiter=' ')

				for plain in reader:
					self.set_plain(*plain)

		except FileNotFoundError:
			Log.warning("file not found")
			pass

	def sync(self):
		with open(self.csv_file_name, 'w') as f:
			writer = csv.writer(f, delimiter=' ')

			for l in self._into_iter_plain():
				writer.writerow(l)


class DictRamDataProvider(dict):
	"""
	A data provider storing data in RAM.
	"""

	def __init__(self, *args, **kwargs):
		dict.__init__(self, *args, **kwargs)
		self.line_to_kv: object = lambda l: (tuple([l[0]] + list(map(int, l[1:-1]))), float(l[-1]))

	def get_plain(self, *key):
		if key not in self.keys():
			raise AssertionError(str(key))

		return self[key]

	def into_iter_plain(self):
		stitch = lambda kv: kv[0] + (kv[1],)

		return map(stitch, self.items())

	def set_plain(self, *args):
		"""
		Adds a sequence of format (VAR, INDEX1, INDEX2, ..., VALUE) into the dictionary
		"""
		assert len(args) >= 2
		k, v = self.line_to_kv(args)
		self[copy.deepcopy(k)] = copy.deepcopy(v)

	def sync(self, *args, **kwargs):
		pass


@dataclass
class DataInterface:
	"""
	Abstraction layer over data storage.
	"""
	provider: object  # Abstraction over storage medium
	schema: Schema

	def clone_as_dict_ram(self, di_type=None):
		"""
		Clones data from the currently used data provider into the new one
		based using an instance of `DictRamDataProvider`.

		Warning: the operation is potentially memory-expensive, and it employs
		no guardrails to prevent memory overspending.
		"""
		if di_type is None:
			di_type = DataInterface

		dict_ram_data_provider = DictRamDataProvider()

		for item in self.provider.into_iter_plain():
			item_copy = copy.deepcopy(item)
			dict_ram_data_provider.set_plain(*item_copy)

		data_interface = di_type(provider=dict_ram_data_provider, schema=copy.deepcopy(self.schema))

		return data_interface

	def update(self, data_interface):
		"""
		Update values using another data interface
		"""

		for item in data_interface.provider.into_iter_plain():
			self.set_plain(*item)

	def get_plain(self, *args, **kwargs):
		return self.provider.get_plain(*args, **kwargs)

	def set_plain(self, *args, **kwargs):
		return self.provider.set_plain(*args, **kwargs)

	def get(self, variable, **indices) -> float:
		plain = self.schema.indices_dict_to_plain(variable, **indices)

		return self.provider.get_plain(*plain)

	def set(self, variable, value, **indices) -> float:
		plain = self.schema.indices_dict_to_plain(variable, **indices)
		self.provider.set_plain(*plain, value)

	def __del__(self):
		self.provider.sync()


class ZeroingDataInterface(DataInterface):
	def get_plain(self, *args, **kwargs):
		try:
			return DataInterface.get_plain(self, *args, **kwargs)
		except AssertionError:
			return 0.0

	def get(self, *args, **kwargs):
		try:
			return DataInterface.get(self, *args, **kwargs)
		except AssertionError:
			return 0.0


@dataclass
class Env:
	row_index: RowIndex
	schema: Schema
	data_interface: DataInterface

	@staticmethod
	def make_from_file(schema_file, storage_file, row_index_variables: list = list(), zeroing_data_interface=False):
		"""
		:param zeroing_data_interface: if true, all missing members will treated as being equal to 0
		"""
		storage_file = pathlib.Path(storage_file)
		schema_file = pathlib.Path(schema_file).resolve()
		storage_provider_type = {
			".csv": PermissiveCsvBufferedDataProvider,
		}
		schema = Schema(filename=schema_file)

		if len(row_index_variables) > 0:
			row_index = RowIndex.make_from_schema(schema, row_index_variables)
		else:
			row_index = None

		try:
			storage_provider = storage_provider_type[storage_file.suffix](str(storage_file))
		except KeyError as e:
			Log.error("Could not find an appropriate storage provider", str(e))
			raise e

		if zeroing_data_interface:
			data_interface = ZeroingDataInterface(provider=storage_provider, schema=schema)
		else:
			data_interface = DataInterface(provider=storage_provider, schema=schema)

		return Env(row_index=row_index, schema=schema, data_interface=data_interface)


@dataclass
class VirtHelper:
	"""
	Enfuses data storage with subject area-related semantics. Pertains to simulation of data exchange in a
	virtualized network (see the 2022 paper)
	"""
	env: Env
	indices_container: list = None
	var_transfer_planned: str = "x"  # How much information was planned to be transferred
	var_transfer_intensity: str = "mm_psi"  # What is the maximum intensity of a channel
	var_transfer_intensity_fraction: str = "m_psi" # What fraction of intensity is being used during the transfer
	var_transfer_intensity_handled: str = "x^"  # How much information has been handled
	var_store_planned: str = "y"
	var_store_intensity: str = "mm_v"
	var_store_intensity_fraction: str = "m_v"
	var_store_intensity_handled: str = "y^"
	var_process_planned: str = "g"
	var_process_intensity: str = "mm_phi"
	var_process_intensity_fraction: str = "m_phi"
	var_process_intensity_handled: str = "g^"
	var_drop_planned: str = "z"
	var_drop_processed: str = "z^"
	var_generate_planned: str = "x_eq"
	var_generate_processed: str = "x_eq^"
	var_weight_processed: str = "alpha_0"  # alpha_g
	var_weight_dropped: str = "alpha_1"  # alpha_z

	def __post_init__(self):
		self.indices_container = ["j", "rho", "l"]
		self.__init_duration()

	def weight_processed(self):
		try:
			ret = self.env.data_interface.get(self.var_weight_processed)
		except KeyError:
			ret = 1.0 - self.env.data_interface.get(self.var_weight_dropped)

		return ret

	def weight_dropped(self):
		try:
			ret = self.env.data_interface.get(self.var_weight_dropped)
		except KeyError:
			ret = 1.0 - self.env.data_interface.get(self.var_weight_processed)

		return ret

	def indices_planned_decompose(self, var, indices_planned_plain):
		"""
		Decomposes indices into j, i, rho, and l. If some is not present, the returned value is none
		"""
		ind = self.env.schema.indices_plain_to_dict(var, *indices_planned_plain)[1]
		j = ind.pop("j", None)
		i = ind.pop("i", None)
		rho = ind.pop("rho", None)
		l = ind.pop("l", None)

		return j, i, rho, l

	def indices_iter_plain(self, index_names):
		return self.env.schema.radix_map_iter(*index_names)

	def indices_container_iter_plain(self):
		return self.indices_iter_plain(self.indices_container)

	def indices_transfer_iter_plain(self):
		return self.indices_iter_plain(self.env.schema.get_var_indices(self.var_transfer_planned))

	def indices_transfer_to_indices_container_receiver(self, indices_transfer_plain):
		assert self.indices_container == ["j", "rho", "l"]
		j, i, rho, l = self.indices_planned_decompose(self.var_transfer_planned, indices_transfer_plain)

		return i, rho, l

	def indices_transfer_to_indices_container_sender(self, indices_transfer_plain):
		assert self.indices_container == ["j", "rho", "l"]
		j, i, rho, l = self.indices_planned_decompose(self.var_transfer_planned, indices_transfer_plain)

		return j, rho, l

	def indices_transfer_is_connected(self, indices):
		"""
		Determine by indices, whether there is a connection b/w j and i
		"""
		j, i, rho, l = self.indices_planned_decompose(self.var_transfer_planned, indices)

		if i == j:
			return False

		intensity = self.env.data_interface.get(self.var_transfer_intensity, j=j, i=i, l=l)
		intensity_fraction = self.env.data_interface.get(self.var_transfer_intensity_fraction, j=j, i=i, rho=rho, l=l)

		return intensity > 0 and intensity_fraction > 0

	def amount_planned_transfer(self, indices_transfer_plain):
		return self.env.data_interface.get_plain(self.var_transfer_planned, *indices_transfer_plain)

	def intensity_fraction_transfer(self, indices_transfer_planned_plain):
		return self.env.data_interface.get_plain(self.var_transfer_intensity_fraction, *indices_transfer_planned_plain)

	def intensity_upper_transfer(self, indices_planned_transfer_plain):
		j, i, rho, l = self.indices_planned_decompose(self.var_transfer_planned, indices_planned_transfer_plain)

		return self.env.data_interface.get(self.var_transfer_intensity, j=j, i=i, l=l)

	def indices_store_to_indices_container(self, indices_store_plain):
		assert self.indices_container == ["j", "rho", "l"]
		j, i, rho, l = self.indices_planned_decompose(self.var_store_planned, indices_store_plain)

		return j, rho, l

	def indices_container_processed_iter_plain(self):
		return self.env.schema.radix_map_iter("j", "rho")

	def indices_store_to_indices_container_processed(self, indices_store_planned_plain):
		"""
		"Processed info. container" ensures connection between store operations across structural stability timespan
		"""
		j, i, rho, l = self.indices_planned_decompose(self.var_store_planned, indices_store_planned_plain)

		return j, rho

	def indices_store_iter_plain(self):
		return self.indices_iter_plain(self.env.schema.get_var_indices(self.var_store_planned))

	def amount_planned_store(self, indices_store):
		return self.env.data_interface.get_plain(self.var_store_planned, *indices_store)

	def intensity_fraction_store(self, indices_store):
		return self.env.data_interface.get_plain(self.var_store_intensity_fraction, *indices_store)

	def intensity_upper_store(self, indices_store):
		j, i, rho, l = self.indices_planned_decompose(self.var_store_planned, indices_store)
		return self.env.data_interface.get(self.var_store_intensity, j=j, l=l)

	def indices_process_iter_plain(self):
		return self.indices_iter_plain(self.env.schema.get_var_indices(self.var_process_planned))

	def amount_planned_process(self, indices_planned_process):
		return self.env.data_interface.get_plain(self.var_process_planned, *indices_planned_process)

	def intensity_fraction_process(self, indices_planned_process):
		j, i, rho, l = self.indices_planned_decompose(self.var_process_planned, indices_planned_process)

		return self.env.data_interface.get(self.var_process_intensity_fraction, j=j, l=l, rho=rho)

	def intensity_upper_process(self, indices_planned_process):
		j, i, rho, l = self.indices_planned_decompose(self.var_process_planned, indices_planned_process)

		return self.env.data_interface.get(self.var_process_intensity, j=j, l=l)

	def indices_process_to_indices_container(self, indices_planned_process):
		j, i, rho, l = self.indices_planned_decompose(self.var_process_planned, indices_planned_process)

		return j, rho, l

	def indices_drop_iter_plain(self):
		return self.indices_iter_plain(self.env.schema.get_var_indices(self.var_drop_planned))

	def amount_planned_drop(self, indices_planned_drop):
		return self.env.data_interface.get_plain(self.var_drop_planned, *indices_planned_drop)

	def intensity_fraction_drop(self, indices_planned_drop):
		return 1.0

	def intensity_upper_drop(self, indices_planned_drop):
		return float("inf")

	def indices_drop_to_indices_container(self, indices_planned_drop):
		j, i, rho, l = self.indices_planned_decompose(self.var_drop_planned, indices_planned_drop)

		return j, rho, l

	def indices_generate_iter_plain(self):
		return self.indices_iter_plain(self.env.schema.get_var_indices(self.var_generate_planned))

	def amount_planned_generate(self, indices_planned_generate):
		return self.env.data_interface.get_plain(self.var_generate_planned, *indices_planned_generate)

	def intensity_upper_generate(self, indices_planned_generate):
		j, i, rho, l = self.indices_planned_decompose(self.var_generate_planned, indices_planned_generate)

		return self.env.data_interface.get_plain(self.var_generate_planned,
			*indices_planned_generate) / self.env.data_interface.get("tl", l=l)

	def indices_generate_to_indices_container(self, indices_planned_generate):
		return indices_planned_generate  # j, rho, l

	def indices_process_l(self, indices_planned_process_plain):
		j, i, rho, l = self.indices_planned_decompose(self.var_process_planned, indices_planned_process_plain)

		return l

	def indices_transfer_l(self, indices_planned_transfer_plain):
		j, i, rho, l = self.indices_planned_decompose(self.var_transfer_planned, indices_planned_transfer_plain)

		return l

	def indices_store_l(self, indices_planned_store_plain):
		j, i, rho, l = self.indices_planned_decompose(self.var_store_planned, indices_planned_store_plain)

		return l

	def indices_drop_l(self, indices_planned_drop_plain):
		j, i, rho, l = self.indices_planned_decompose(self.var_drop_planned, indices_planned_drop_plain)

		return l

	def indices_generate_l(self, indices_planned_generate_plain):
		j, i, rho, l = self.indices_planned_decompose(self.var_generate_planned, indices_planned_generate_plain)

		return l

	def tl(self, l):
		return self.env.data_interface.get("tl", l=l)

	def __init_duration(self):
		self.__tl_bounds = []
		duration = 0.0

		for l in range(self.env.schema.get_index_bound("l")):
			duration += self.env.data_interface.get("tl", l=l)
			self.__tl_bounds.append(duration)

	def l_to_t_bound(self, l):
		return self.__tl_bounds[l]

	def t_to_l(self, t):
		for l, t_bound in enumerate(self.__tl_bounds):
			if t < t_bound:
				return l

	def duration(self):
		return self.__tl_bounds[-1]
