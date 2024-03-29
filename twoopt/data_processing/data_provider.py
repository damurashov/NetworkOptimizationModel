"""

`DataProvider` is a low-level memory access API which encapsulates working with
files, databases, or RAM under an interface.

`DataProvider` is similar to `DataInterface` (see "data_interface.py") in a
sense that both are used for data accessing. However, `DataInterface` does
not know anything about the underlying storage mechanism, while
`DataProvider` is complete unaware about business logic, as it only deals
with plain `(K, V)` rows.

"""

import csv
import dataclasses
import io
import os
import re
import twoopt.utility.logging


log = twoopt.utility.logging.Log(file=__file__)


class DataProviderBase:
    """
    Represents underlying data as a list of entries. Can be thought of
    as a list of tuples

    [
        (VARIABLE_NAME, COMPLEX_IDENTIFIER_PART_1, ..., COMPLEX_IDENTIFIER_PART_N, VALUE),
        (VARIABLE_NAME, COMPLEX_IDENTIFIER_PART_1, ..., COMPLEX_IDENTIFIER_PART_N, VALUE),
        ...
    ]

    If the implementor cannot satisfy the request due to lack of data, it
    must raise `twoopt.data_processing.data_interface.NoDataError(...)`
    """

    def data(self, *composite_tuple_identifier):
        pass

    def set_data(self, value, *composite_tuple_identifier):
        pass

    def into_iter(self):
        """
        Iterates over stored values employing the following format:

        ```
        [
            (VARIABLE_NAME, COMPLEX_IDENTIFIER_PART_1, ..., COMPLEX_IDENTIFIER_PART_N, VALUE),
            (VARIABLE_NAME, COMPLEX_IDENTIFIER_PART_1, ..., COMPLEX_IDENTIFIER_PART_N, VALUE),
            ...
        ]
        ```
        """
        pass

    def set_data_from_rows(self, iterable_rows):
        """
        Rows must have the following format: `(VARIABLE, ID1, ID2, ..., VALUE)`
        """
        for row in iterable_rows:
            assert len(row) >= 2
            value = row[-1]
            composite_key = row[0:-1]
            self.set_data(value, *composite_key)

    def set_data_from_data_provider(self, other):
        for data in other.into_iter():
            composite_tuple_identifier = data[:-1]
            value = data[-1]
            self.set_data(value, *composite_tuple_identifier)


class RamDataProvider(dict, DataProviderBase):

    def __init__(self, *args, **kwargs):
        dict.__init__(self, *args, **kwargs)
        DataProviderBase.__init__(self)

    def data(self, *composite_tuple_identifier):
        import twoopt.data_processing.data_interface

        if composite_tuple_identifier not in self:
            raise twoopt.data_processing.data_interface.NoDataError(composite_tuple_identifier)

        try:
            return self[composite_tuple_identifier]
        except KeyError:
            raise twoopt.data_processing.data_interface.NoDataError(str(composite_tuple_identifier))

    def set_data(self, value, *composite_tuple_identifier):
        self[composite_tuple_identifier] = value

    def into_iter(self):
        for k, v in self.items():
            yield *k, v


@dataclasses.dataclass
class PermissiveCsvBufferedDataProvider(dict, DataProviderBase):
    """
    CSV with mixed whitespace / tab delimiters.

    Guarantees and ensures that VARIABLE has type `str`, indices have type
    `int`, and VALUE has type `float`
    """
    csv_file_name: str
    sync_on_object_destruction = True

    def __del__(self):
        if self.sync_on_object_destruction:
            log.info(PermissiveCsvBufferedDataProvider, "Dumping changes into CSV")
            self.sync()

    def data(self, *composite_tuple_identifier):
        import twoopt.data_processing.data_interface

        try:
            return self.get_plain(*composite_tuple_identifier)
        except:
            raise twoopt.data_processing.data_interface.NoDataError(composite_tuple_identifier)

    def set_data(self, value, *composite_tuple_identifier):
        self.set_plain(*composite_tuple_identifier, value)

    def get_plain(self, *key):
        assert key in self.keys()
        return self[key]

    def set_plain(self, *args):
        """
        Adds a sequence of format (VAR, INDEX1, INDEX2, ..., VALUE) into the dictionary
        """
        if not (len(args) >= 2):
            raise ValueError(f"Data format has been violated: (VAR, [INDICES, ] VALUE). Got: `{args}`")

        line_to_kv: object = lambda l: (tuple([l[0]] + list(map(int, l[1:-1]))), float(l[-1]))
        k, v = line_to_kv(args)
        self[k] = v

    def into_iter(self):
        stitch = lambda kv: kv[0] + (kv[1],)

        return map(stitch, self.items())

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
            pass

    def sync(self):
        with open(self.csv_file_name, 'w') as f:
            writer = csv.writer(f, delimiter=' ')

            for l in self.into_iter():
                writer.writerow(l)
