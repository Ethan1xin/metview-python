# (C) Copyright 2017- ECMWF.
#
# This software is licensed under the terms of the Apache Licence Version 2.0
# which can be obtained at http://www.apache.org/licenses/LICENSE-2.0.
#
# In applying this licence, ECMWF does not waive the privileges and immunities
# granted to it by virtue of its status as an intergovernmental organisation
# nor does it submit to any jurisdiction.


import datetime
import keyword
import os
import pkgutil
import signal
import tempfile
import builtins
from enum import Enum

import cffi
import numpy as np


__version__ = "1.6.0"


def string_from_ffi(s):
    return ffi.string(s).decode("utf-8")


# -----------------------------------------------------------------------------
#                                 Startup
# -----------------------------------------------------------------------------


class MetviewInvoker:
    """Starts a new Metview session on construction and terminates it on program exit"""

    def __init__(self):
        """
        Constructor - starts a Metview session and reads its environment information
        Raises an exception if Metview does not respond within so-many seconds
        """

        self.debug = os.environ.get("METVIEW_PYTHON_DEBUG", "0") == "1"

        # check whether we're in a running Metview session
        if "METVIEW_TITLE_PROD" in os.environ:
            self.persistent_session = True
            self.info_section = {"METVIEW_LIB": os.environ["METVIEW_LIB"]}
            return

        import atexit
        import time
        import subprocess

        if self.debug:
            print("MetviewInvoker: Invoking Metview")
        self.persistent_session = False
        self.metview_replied = False
        self.metview_startup_timeout = int(
            os.environ.get("METVIEW_PYTHON_START_TIMEOUT", "8")
        )  # seconds

        # start Metview with command-line parameters that will let it communicate back to us
        env_file = tempfile.NamedTemporaryFile(mode="rt")
        pid = os.getpid()
        # print('PYTHON:', pid, ' ', env_file.name, ' ', repr(signal.SIGUSR1))
        signal.signal(signal.SIGUSR1, self.signal_from_metview)
        # p = subprocess.Popen(['metview', '-edbg', 'tv8 -a', '-slog', '-python-serve',
        #     env_file.name, str(pid)], stdout=subprocess.PIPE)
        metview_startup_cmd = os.environ.get("METVIEW_PYTHON_START_CMD", "metview")
        metview_flags = [
            metview_startup_cmd,
            "-nocreatehome",
            "-python-serve",
            env_file.name,
            str(pid),
        ]
        if self.debug:
            metview_flags.insert(2, "-slog")
            print("Starting Metview using these command args:")
            print(metview_flags)

        try:
            subprocess.Popen(metview_flags)
        except Exception as exp:
            print(
                "Could not run the Metview executable ('" + metview_startup_cmd + "'); "
                "check that the binaries for Metview (version 5 at least) are installed "
                "and are in the PATH."
            )
            raise exp

        # wait for Metview to respond...
        wait_start = time.time()
        while not (self.metview_replied) and (
            time.time() - wait_start < self.metview_startup_timeout
        ):
            time.sleep(0.001)

        if not (self.metview_replied):
            raise Exception(
                'Command "metview" did not respond within '
                + str(self.metview_startup_timeout)
                + " seconds. This timeout is configurable by setting "
                "environment variable METVIEW_PYTHON_START_TIMEOUT in seconds. "
                "At least Metview 5 is required, so please ensure it is in your PATH, "
                "as earlier versions will not work with the Python interface."
            )

        self.read_metview_settings(env_file.name)
        env_file.close()

        # when the Python session terminates, we should destroy this object so that the Metview
        # session is properly cleaned up. We can also do this in a __del__ function, but there can
        # be problems with the order of cleanup - e.g. the 'os' module might be deleted before
        # this destructor is called.
        atexit.register(self.destroy)

    def destroy(self):
        """Kills the Metview session. Raises an exception if it could not do it."""

        if self.persistent_session:
            return

        if self.metview_replied:
            if self.debug:
                print("MetviewInvoker: Closing Metview")
            metview_pid = self.info("EVENT_PID")
            try:
                os.kill(int(metview_pid), signal.SIGUSR1)
            except Exception as exp:
                print("Could not terminate the Metview process pid=" + metview_pid)
                raise exp

    def signal_from_metview(self, *args):
        """Called when Metview sends a signal back to Python to say that it's started"""
        # print ('PYTHON: GOT SIGNAL BACK FROM METVIEW!')
        self.metview_replied = True

    def read_metview_settings(self, settings_file):
        """Parses the settings file generated by Metview and sets the corresponding env vars"""
        import configparser

        cf = configparser.ConfigParser()
        cf.read(settings_file)
        env_section = cf["Environment"]
        for envar in env_section:
            # print('set ', envar.upper(), ' = ', env_section[envar])
            os.environ[envar.upper()] = env_section[envar]
        self.info_section = cf["Info"]

    def info(self, key):
        """Returns a piece of Metview information that was not set as an env var"""
        return self.info_section[key]

    def store_signal_handlers(self):
        """Stores the set of signal handlers that Metview will override"""
        self.sigint = signal.getsignal(signal.SIGINT)
        self.sighup = signal.getsignal(signal.SIGHUP)
        self.sighquit = signal.getsignal(signal.SIGQUIT)
        self.sigterm = signal.getsignal(signal.SIGTERM)
        self.sigalarm = signal.getsignal(signal.SIGALRM)

    def restore_signal_handlers(self):
        """Restores the set of signal handlers that Metview has overridden"""
        signal.signal(signal.SIGINT, self.sigint)
        signal.signal(signal.SIGHUP, self.sighup)
        signal.signal(signal.SIGQUIT, self.sighquit)
        signal.signal(signal.SIGTERM, self.sigterm)
        signal.signal(signal.SIGALRM, self.sigalarm)


mi = MetviewInvoker()

try:
    ffi = cffi.FFI()
    ffi.cdef(pkgutil.get_data("metview", "metview.h").decode("ascii"))
    mv_lib = mi.info("METVIEW_LIB")
    # is there a more general way to add to a path to a list of paths?
    os.environ["LD_LIBRARY_PATH"] = mv_lib + ":" + os.environ.get("LD_LIBRARY_PATH", "")

    try:
        # Linux / Unix systems
        lib = ffi.dlopen(os.path.join(mv_lib, "libMvMacro.so"))
    except OSError:
        # MacOS systems
        lib = ffi.dlopen(os.path.join(mv_lib, "libMvMacro"))

except Exception as exp:
    print(
        "Error loading Metview/libMvMacro. LD_LIBRARY_PATH="
        + os.environ.get("LD_LIBRARY_PATH", "")
    )
    raise exp


# The C/C++ code behind lib.p_init() will call marsinit(), which overrides various signal
# handlers. We don't necessarily want this when running a Python script - we should use
# the default Python behaviour for handling signals, so we save the current signals
# before calling p_init() and restore them after.
mi.store_signal_handlers()
lib.p_init()
mi.restore_signal_handlers()

# fix for binder-hosted notebooks, where PWD and os.cwd() do not seem to be in sync
os.putenv("PWD", os.getcwd())

# -----------------------------------------------------------------------------
#                        Classes to handle complex Macro types
# -----------------------------------------------------------------------------


class Value:
    def __init__(self, val_pointer):
        self.val_pointer = val_pointer
        self.pickled = False

    def push(self):
        if self.val_pointer is None:
            lib.p_push_nil()
        else:
            lib.p_push_value(self.val_pointer)

    # if we steal a value pointer from a temporary Value object, we need to
    # ensure that the Metview Value is not destroyed when the temporary object
    # is destroyed by setting its pointer to None
    def steal_val_pointer(self, other):
        self.val_pointer = other.val_pointer
        other.val_pointer = None

    def set_temporary(self, flag):
        lib.p_set_temporary(self.val_pointer, flag)

    # enable a more object-oriented interface, e.g. a = fs.interpolate(10, 29.4)
    def __getattr__(self, fname):
        def call_func_with_self(*args, **kwargs):
            return call(fname, self, *args, **kwargs)

        return call_func_with_self

    # on destruction, ensure that the Macro Value is also destroyed.
    # note the exception - if the variable has been pickled, then there
    # may be a temporary file that another process will want to use
    # later, so in this case we do not destroy the Macro Value.
    def __del__(self):
        try:
            if self.val_pointer is not None and lib is not None:
                if not self.pickled:
                    lib.p_destroy_value(self.val_pointer)
                    self.val_pointer = None
        except Exception as exp:
            print("Could not destroy Metview variable ", self)
            raise exp


class Request(dict, Value):
    verb = "UNKNOWN"

    def __init__(self, req, myverb=None):
        self.val_pointer = None

        # initialise from Python object (dict/Request)
        if isinstance(req, dict):
            self.update(req)
            self.to_metview_style()
            if isinstance(req, Request):
                self.verb = req.verb
                self.val_pointer = req.val_pointer
            else:
                if myverb is not None:
                    self.set_verb(myverb)

        # initialise from a Macro pointer
        else:
            Value.__init__(self, req)
            self.verb = string_from_ffi(lib.p_get_req_verb(req))
            n = lib.p_get_req_num_params(req)
            for i in range(0, n):
                param = string_from_ffi(lib.p_get_req_param(req, i))
                self[param] = self[param]
            # self['_MACRO'] = 'BLANK'
            # self['_PATH']  = 'BLANK'

    def __str__(self):
        return "VERB: " + self.verb + super().__str__()

    # translate Python classes into Metview ones where needed
    def to_metview_style(self):
        for k in list(self):

            # bool -> on/off
            v = self.get(k)  # self[k] returns 1 for True
            if isinstance(v, bool):
                conversion_dict = {True: "on", False: "off"}
                self[k] = conversion_dict[v]

            # class_ -> class (because 'class' is a Python keyword and cannot be
            # used as a named parameter)
            elif k == "class_":
                self["class"] = v
                del self["class_"]

    def set_verb(self, v):
        self.verb = v

    def get_verb(self):
        return self.verb

    def push(self):
        # if we have a pointer to a Metview Value, then use that because it's more
        # complete than the dict
        if self.val_pointer:
            Value.push(self)
        else:
            r = lib.p_new_request(self.verb.encode("utf-8"))

            # to populate a request on the Macro side, we push each
            # value onto its stack, and then tell it to create a new
            # parameter with that name for the request. This allows us to
            # use Macro to handle the addition of complex data types to
            # a request
            for k, v in self.items():
                push_arg(v)
                lib.p_set_request_value_from_pop(r, k.encode("utf-8"))

            lib.p_push_request(r)

    def __getitem__(self, index):
        return subset(self, index)


def push_bytes(b):
    lib.p_push_string(b)


def push_str(s):
    push_bytes(s.encode("utf-8"))


def push_list(lst):
    # ask Metview to create a new list, then add each element by
    # pusing it onto the stack and asking Metview to pop it off
    # and add it to the list
    mlist = lib.p_new_list(len(lst))
    for i, val in enumerate(lst):
        push_arg(val)
        lib.p_add_value_from_pop_to_list(mlist, i)
    lib.p_push_list(mlist)


def push_date(d):
    lib.p_push_datestring(np.datetime_as_string(d).encode("utf-8"))


def push_datetime(d):
    lib.p_push_datestring(d.isoformat().encode("utf-8"))


def push_datetime_date(d):
    s = d.isoformat() + "T00:00:00"
    lib.p_push_datestring(s.encode("utf-8"))


def push_vector(npa):

    # if this is a view with a non-contiguous step, make a copy so that
    # we get contiguous data
    if not npa.flags["C_CONTIGUOUS"]:
        npa = npa.copy()

    # convert numpy array to CData
    dtype = npa.dtype
    if dtype == np.float64:  #  can directly pass the data buffer
        cffi_buffer = ffi.cast("double*", npa.ctypes.data)
        lib.p_push_vector_from_double_array(cffi_buffer, len(npa), np.nan)
    elif dtype == np.float32:  #  can directly pass the data buffer
        cffi_buffer = ffi.cast("float*", npa.ctypes.data)
        lib.p_push_vector_from_float32_array(cffi_buffer, len(npa), np.nan)
    elif dtype == np.bool:  # convert first to float32
        f32_array = npa.astype(np.float32)
        cffi_buffer = ffi.cast("float*", f32_array.ctypes.data)
        lib.p_push_vector_from_float32_array(cffi_buffer, len(f32_array), np.nan)
    elif dtype == np.int:  # convert first to float64
        f64_array = npa.astype(np.float64)
        cffi_buffer = ffi.cast("double*", f64_array.ctypes.data)
        lib.p_push_vector_from_double_array(cffi_buffer, len(f64_array), np.nan)
    else:
        raise TypeError(
            "Only float32 and float64 numPy arrays can be passed to Metview, not ",
            npa.dtype,
        )


class File(Value):
    def __init__(self, val_pointer):
        Value.__init__(self, val_pointer)


class FileBackedValue(Value):
    def __init__(self, val_pointer):
        Value.__init__(self, val_pointer)

    def write(self, filename):
        return write(filename, self)

    def url(self):
        # ask Metview for the file relating to this data (Metview will write it if necessary)
        return string_from_ffi(lib.p_data_path(self.val_pointer))


class FileBackedValueWithOperators(FileBackedValue):
    def __init__(self, val_pointer):
        FileBackedValue.__init__(self, val_pointer)

    def __add__(self, other):
        return add(self, other)

    def __radd__(self, other):
        return add(other, self)

    def __sub__(self, other):
        return sub(self, other)

    def __rsub__(self, other):
        return sub(other, self)

    def __mul__(self, other):
        return prod(self, other)

    def __rmul__(other, self):
        return prod(other, self)

    def __truediv__(self, other):
        return div(self, other)

    def __rtruediv__(self, other):
        return div(other, self)

    def __pow__(self, other):
        return power(self, other)

    def __rpow__(self, other):
        return power(other, self)

    def __ge__(self, other):
        return greater_equal_than(self, other)

    def __gt__(self, other):
        return greater_than(self, other)

    def __le__(self, other):
        return lower_equal_than(self, other)

    def __lt__(self, other):
        return lower_than(self, other)

    def __eq__(self, other):
        return equal(self, other)

    def __ne__(self, other):
        return met_not_eq(self, other)

    def __pos__(self):
        return self

    def __neg__(self):
        return 0.0 - self

    def __abs__(self):
        return self.abs()

    def __and__(self, other):
        return met_and(self, other)

    def __or__(self, other):
        return met_or(self, other)

    def __invert__(self):
        return met_not(self)


class ContainerValueIterator:
    def __init__(self, data):
        self.index = 0
        self.data = data

    def __iter__(self):
        return self

    def __next__(self):
        if self.index >= len(self.data):
            self.index = 0
            raise StopIteration
        else:
            self.index += 1
            return self.data[self.index - 1]


# ContainerValue
# val_pointer - pointer to a C++ Value
# macro_index_base - 0 or 1 - what do Macro indexing functions expect?
# element_types - the type of elements that the container contains
# support_slicing - does the container suppoer slicing?
class ContainerValue(Value):
    def __init__(self, val_pointer, macro_index_base, element_types, support_slicing):
        Value.__init__(self, val_pointer)
        self.macro_index_base = macro_index_base
        self.element_types = element_types
        self.support_slicing = support_slicing

    def __len__(self):
        if self.val_pointer is None:
            return 0
        else:
            return int(count(self))

    def __getitem__(self, index):
        if isinstance(index, slice):
            if self.support_slicing:
                indices = index.indices(len(self))
                fields = [self[i] for i in range(*indices)]
                if len(fields) == 0:
                    return None
                else:
                    f = fields[0]
                    for i in range(1, len(fields)):
                        f = merge(f, fields[i])
                    return f
            else:
                raise IndexError(
                    "This object does not support extended slicing: " + str(self)
                )
        else:  # normal index
            if isinstance(index, str):  # can have a string as an index
                return subset(self, index)
            elif isinstance(index, np.ndarray):  # can have an array as an index
                return subset(self, index + self.macro_index_base)
            else:
                if index < 0:  # negative index valid for range [-len..-1]
                    c = int(count(self))
                    if index >= -c:
                        index = c + index
                    else:
                        raise IndexError("Index " + str(index) + " invalid ", self)
                return subset(
                    self, index + self.macro_index_base
                )  # numeric index: 0->1-based

    def __setitem__(self, index, value):
        if isinstance(value, self.element_types):
            if isinstance(index, int):
                index += self.macro_index_base
            push_arg(index)
            push_arg(value)
            lib.p_set_subvalue_from_arg_stack(self.val_pointer)
        else:
            raise IndexError("Cannot assign ", value, " as element of ", self)

    def __iter__(self):
        return ContainerValueIterator(self)


class Fieldset(FileBackedValueWithOperators, ContainerValue):
    def __init__(self, val_pointer=None, path=None, fields=None):
        FileBackedValueWithOperators.__init__(self, val_pointer)
        ContainerValue.__init__(
            self,
            val_pointer=val_pointer,
            macro_index_base=1,
            element_types=Fieldset,
            support_slicing=True,
        )

        if (path is not None) and (fields is not None):
            raise ValueError("Fieldset cannot take both path and fields")

        if path is not None:
            temp = read(path)
            self.steal_val_pointer(temp)

        if fields is not None:
            for f in fields:
                self.append(f)

    def append(self, other):
        temp = merge(self, other)
        if self.val_pointer != None:  #  we will overwrite ourselves, so delete
            lib.p_destroy_value(self.val_pointer)
        self.steal_val_pointer(temp)

    def to_dataset(self):
        # soft dependency on cfgrib
        try:
            from cfgrib import xarray_store
        except ImportError:
            print(
                "Package cfgrib/xarray_store not found. Try running 'pip install cfgrib'."
            )
            raise
        dataset = xarray_store.open_dataset(self.url())
        return dataset

    def __getstate__(self):
        # used for pickling
        # we cannot (and do not want to) directly pickle the Value pointer
        # so we remove it and put instead the path to the file
        d = dict(self.__dict__)
        del d["val_pointer"]
        d["url_path"] = self.url()
        self.pickled = True
        return d

    def __setstate__(self, state):
        # used for un-pickling
        # read the data from the pickled path
        self.__dict__.update(state)
        self.__init__(val_pointer=None, path=state["url_path"])


class Bufr(FileBackedValue):
    def __init__(self, val_pointer):
        FileBackedValue.__init__(self, val_pointer)


class Geopoints(FileBackedValueWithOperators, ContainerValue):
    def __init__(self, val_pointer):
        FileBackedValueWithOperators.__init__(self, val_pointer)
        ContainerValue.__init__(
            self,
            val_pointer=val_pointer,
            macro_index_base=0,
            element_types=(np.ndarray, list),
            support_slicing=False,
        )

    def to_dataframe(self):
        try:
            import pandas as pd
        except ImportError:
            print("Package pandas not found. Try running 'pip install pandas'.")
            raise

        # create a dictionary of columns (note that we do not include 'time'
        # because it is incorporated into 'date')
        cols = self.columns()
        if "time" in cols:
            cols.remove("time")

        pddict = {}
        for c in cols:
            pddict[c] = self[c]

        df = pd.DataFrame(pddict)
        return df


class NetCDF(FileBackedValueWithOperators):
    def __init__(self, val_pointer):
        FileBackedValueWithOperators.__init__(self, val_pointer)

    def to_dataset(self):
        # soft dependency on xarray
        try:
            import xarray as xr
        except ImportError:
            print("Package xarray not found. Try running 'pip install xarray'.")
            raise
        dataset = xr.open_dataset(self.url())
        return dataset


class Odb(FileBackedValue):
    def __init__(self, val_pointer):
        FileBackedValue.__init__(self, val_pointer)

    def to_dataframe(self):
        try:
            import pandas as pd
        except ImportError:
            print("Package pandas not found. Try running 'pip install pandas'.")
            raise

        cols = self.columns()
        pddict = {}

        for col in cols:
            pddict[col] = self.values(col)

        df = pd.DataFrame(pddict)
        return df


class Table(FileBackedValue):
    def __init__(self, val_pointer):
        FileBackedValue.__init__(self, val_pointer)

    def to_dataframe(self):
        try:
            import pandas as pd
        except ImportError:
            print("Package pandas not found. Try running 'pip install pandas'.")
            raise

        df = pd.read_csv(self.url())
        return df


class GeopointSet(FileBackedValueWithOperators, ContainerValue):
    def __init__(self, val_pointer):
        FileBackedValueWithOperators.__init__(self, val_pointer)
        ContainerValue.__init__(self, val_pointer, 1, Geopoints, False)


# -----------------------------------------------------------------------------
#                        Pushing data types to Macro
# -----------------------------------------------------------------------------


def dataset_to_fieldset(val, **kwarg):
    # we try to import xarray as locally as possible to reduce startup time
    # try to write the xarray as a GRIB file, then read into a fieldset
    import xarray as xr
    import cfgrib

    if not isinstance(val, xr.core.dataset.Dataset):
        raise TypeError(
            "dataset_to_fieldset requires a variable of type xr.core.dataset.Dataset;"
            " was supplied with ",
            builtins.type(val),
        )

    f, tmp = tempfile.mkstemp(".grib")
    os.close(f)

    try:
        # could add keys, e.g. grib_keys={'centre': 'ecmf'})
        cfgrib.to_grib(val, tmp, **kwarg)
    except:
        print(
            "Error trying to write xarray dataset to GRIB for conversion to Metview Fieldset"
        )
        raise

    # TODO: tell Metview that this is a temporary file that should be deleted when no longer needed
    fs = read(tmp)
    fs.set_temporary(1)
    return fs


def push_xarray_dataset(val):
    fs = dataset_to_fieldset(val)
    fs.push()


# try_to_push_complex_type exists as a separate function so that we don't have
# to import xarray at the top of the module - this saves some time on startup
def try_to_push_complex_type(val):
    import xarray as xr

    if isinstance(val, xr.core.dataset.Dataset):
        push_xarray_dataset(val)
    else:
        raise TypeError(
            "Cannot push this type of argument to Metview: ", builtins.type(val)
        )


class ValuePusher:
    """Class to handle pushing values to the Macro library"""

    def __init__(self):
        # a set of pairs linking value types with functions to push them to Macro
        # note that Request must come before dict, because a Request inherits from dict;
        # this ordering requirement also means we should use list or tuple instead of a dict
        self.funcs = (
            (float, lambda n: lib.p_push_number(n)),
            ((int, np.number), lambda n: lib.p_push_number(float(n))),
            (str, lambda n: push_str(n)),
            (Request, lambda n: n.push()),
            (dict, lambda n: Request(n).push()),
            ((list, tuple), lambda n: push_list(n)),
            (type(None), lambda n: lib.p_push_nil()),
            (FileBackedValue, lambda n: n.push()),
            (np.datetime64, lambda n: push_date(n)),
            (datetime.datetime, lambda n: push_datetime(n)),
            (datetime.date, lambda n: push_datetime_date(n)),
            (np.ndarray, lambda n: push_vector(n)),
            (File, lambda n: n.push()),
        )

    def push_value(self, val):
        for typekey, typefunc in self.funcs:
            if isinstance(val, typekey):
                typefunc(val)
                return 1

        # if we haven't returned yet, then try the more complex types
        try_to_push_complex_type(val)
        return 1


vp = ValuePusher()


def push_arg(n):
    return vp.push_value(n)


def dict_to_pushed_args(d):

    # push each key and value onto the argument stack
    for k, v in d.items():
        push_str(k)
        push_arg(v)

    return 2 * len(d)  # return the number of arguments generated


# -----------------------------------------------------------------------------
#                        Returning data types from Macro
# -----------------------------------------------------------------------------


def list_from_metview(val):

    mlist = lib.p_value_as_list(val)
    result = []
    n = lib.p_list_count(mlist)
    all_vectors = True
    for i in range(0, n):
        mval = lib.p_list_element_as_value(mlist, i)
        v = value_from_metview(mval)
        if all_vectors and not isinstance(v, np.ndarray):
            all_vectors = False
        result.append(v)

    # if this is a list of vectors, then create a 2-D numPy array
    if all_vectors and n > 0:
        result = np.stack(result, axis=0)

    # delete the Metview list - this will decrement the reference counts of its objects
    lib.p_destroy_value(val)

    return result


def datestring_from_metview(val):

    mdate = string_from_ffi(lib.p_value_as_datestring(val))
    dt = datetime.datetime.strptime(mdate, "%Y-%m-%dT%H:%M:%S")
    return dt


def vector_from_metview(val):

    vec = lib.p_value_as_vector(val, np.nan)

    n = lib.p_vector_count(vec)
    s = lib.p_vector_elem_size(vec)

    if s == 4:
        nptype = np.float32
        b = lib.p_vector_float32_array(vec)
    elif s == 8:
        nptype = np.float64
        b = lib.p_vector_double_array(vec)
    else:
        raise Exception("Metview vector data type cannot be handled: ", s)

    bsize = n * s
    c_buffer = ffi.buffer(b, bsize)
    np_array = (
        np.frombuffer(c_buffer, dtype=nptype)
    ).copy()  # copy so that we can destroy
    lib.p_destroy_value(val)
    return np_array


def handle_error(val):
    msg = string_from_ffi(lib.p_error_message(val))
    if "Service" in msg and "Examiner" in msg:
        return None
    else:
        return Exception("Metview error: " + (msg))


def string_from_metview(val):
    return string_from_ffi(lib.p_value_as_string(val))


class MvRetVal(Enum):
    tnumber = 0
    tstring = 1
    tgrib = 2
    trequest = 3
    tbufr = 4
    tgeopts = 5
    tlist = 6
    tnetcdf = 7
    tnil = 8
    terror = 9
    tdate = 10
    tvector = 11
    todb = 12
    ttable = 13
    tgptset = 14
    tfile = 15
    tunknown = 99


class ValueReturner:
    """Class to handle return values from the Macro library"""

    def __init__(self):
        self.funcs = {}
        self.funcs[MvRetVal.tnumber.value] = lambda val: lib.p_value_as_number(val)
        self.funcs[MvRetVal.tstring.value] = lambda val: string_from_metview(val)
        self.funcs[MvRetVal.tgrib.value] = lambda val: Fieldset(val)
        self.funcs[MvRetVal.trequest.value] = lambda val: Request(val)
        self.funcs[MvRetVal.tbufr.value] = lambda val: Bufr(val)
        self.funcs[MvRetVal.tgeopts.value] = lambda val: Geopoints(val)
        self.funcs[MvRetVal.tlist.value] = lambda val: list_from_metview(val)
        self.funcs[MvRetVal.tnetcdf.value] = lambda val: NetCDF(val)
        self.funcs[MvRetVal.tnil.value] = lambda val: None
        self.funcs[MvRetVal.terror.value] = lambda val: handle_error(val)
        self.funcs[MvRetVal.tdate.value] = lambda val: datestring_from_metview(val)
        self.funcs[MvRetVal.tvector.value] = lambda val: vector_from_metview(val)
        self.funcs[MvRetVal.todb.value] = lambda val: Odb(val)
        self.funcs[MvRetVal.ttable.value] = lambda val: Table(val)
        self.funcs[MvRetVal.tgptset.value] = lambda val: GeopointSet(val)
        self.funcs[MvRetVal.tfile.value] = lambda val: File(val)

    def translate_return_val(self, val):
        rt = lib.p_value_type(val)
        try:
            return self.funcs[rt](val)
        except Exception:
            raise Exception(
                "value_from_metview got an unhandled return type: " + str(rt)
            )


vr = ValueReturner()


def value_from_metview(val):
    retval = vr.translate_return_val(val)
    if isinstance(retval, Exception):
        raise retval
    return retval


# -----------------------------------------------------------------------------
#                        Creating and calling Macro functions
# -----------------------------------------------------------------------------


def _call_function(mfname, *args, **kwargs):

    nargs = 0

    for n in args:
        actual_n_args = push_arg(n)
        nargs += actual_n_args

    merged_dict = {}
    merged_dict.update(kwargs)
    if len(merged_dict) > 0:
        dn = dict_to_pushed_args(Request(merged_dict))
        nargs += dn

    lib.p_call_function(mfname.encode("utf-8"), nargs)


def make(mfname):
    def wrapped(*args, **kwargs):
        err = _call_function(mfname, *args, **kwargs)
        if err:
            pass  # throw Exceception

        val = lib.p_result_as_value()
        return value_from_metview(val)

    return wrapped


def bind_functions(namespace, module_name=None):
    """Add to the module globals all metview functions except operators like: +, &, etc."""
    for metview_name in make("dictionary")():
        if metview_name.isidentifier():
            python_name = metview_name
            # NOTE: we append a '_' to metview functions that clash with python reserved keywords
            #   as they cannot be used as identifiers, for example: 'in' -> 'in_'
            if keyword.iskeyword(metview_name):
                python_name += "_"
            python_func = make(metview_name)
            python_func.__name__ = python_name
            python_func.__qualname__ = python_name
            if module_name:
                python_func.__module__ = module_name
            namespace[python_name] = python_func
        # else:
        #    print('metview function %r not bound to python' % metview_name)

    # HACK: some fuctions are missing from the 'dictionary' call.
    namespace["neg"] = make("neg")
    namespace["nil"] = make("nil")
    namespace["div"] = div
    namespace["mod"] = mod
    # override some functions that need special treatment
    # FIXME: this needs to be more structured
    namespace["plot"] = plot
    namespace["setoutput"] = setoutput
    namespace["metzoom"] = metzoom
    namespace["version_info"] = version_info
    namespace["dataset_to_fieldset"] = dataset_to_fieldset
    namespace["download_gallery_data"] = download_gallery_data

    namespace["Fieldset"] = Fieldset
    namespace["Request"] = Request


# some explicit bindings are used here
add = make("+")
call = make("call")
count = make("count")
div = make("/")
download = make("download")
equal = make("=")
filter = make("filter")
greater_equal_than = make(">=")
greater_than = make(">")
lower_equal_than = make("<=")
lower_than = make("<")
merge = make("&")
met_not_eq = make("<>")
met_plot = make("plot")
mod = make("mod")
nil = make("nil")
png_output = make("png_output")
power = make("^")
prod = make("*")
ps_output = make("ps_output")
read = make("read")
met_setoutput = make("setoutput")
metzoom = make("metzoom")
sub = make("-")
subset = make("[]")
met_and = make("and")
met_or = make("or")
met_not = make("not")
met_version_info = make("version_info")
write = make("write")


# call the C++ version_info() function and add the version of the
# Python bindings to the resulting dict
def version_info():
    binary_info = dict(met_version_info())
    binary_info["metview_python_version"] = __version__
    return binary_info


# -----------------------------------------------------------------------------
#                        Particular code for calling the plot() command
# -----------------------------------------------------------------------------


class Plot:
    def __init__(self):
        self.plot_to_jupyter = False
        self.jupyter_args = {}

    def __call__(self, *args, **kwargs):
        if self.plot_to_jupyter:
            f, tmp = tempfile.mkstemp(".png")
            os.close(f)

            base, ext = os.path.splitext(tmp)

            self.jupyter_args.update(
                output_name=base, output_name_first_page_number="off"
            )
            met_setoutput(png_output(self.jupyter_args))
            met_plot(*args)

            image = Image(tmp)
            os.unlink(tmp)
            return image
        else:
            map_outputs = {
                "png": png_output,
                "ps": ps_output,
            }
            if "output_type" in kwargs:
                output_function = map_outputs[kwargs["output_type"].lower()]
                kwargs.pop("output_type")
                met_plot(output_function(kwargs), *args)
            else:
                met_plot(*args)
            # the Macro plot command returns an empty definition, but
            # None is better for Python
            return None


plot = Plot()


# On a test system, importing IPython took approx 0.5 seconds, so to avoid that hit
# under most circumstances, we only import it when the user asks for Jupyter
# functionality. Since this occurs within a function, we need a little trickery to
# get the IPython functions into the global namespace so that the plot object can use them
def setoutput(*args, **kwargs):
    if "jupyter" in args:
        try:
            global Image
            global get_ipython
            IPython = __import__("IPython", globals(), locals())
            Image = IPython.display.Image
            get_ipython = IPython.get_ipython
        except ImportError as imperr:
            print("Could not import IPython module - plotting to Jupyter will not work")
            raise imperr

        # test whether we're in the Jupyter environment
        if get_ipython() is not None:
            plot.plot_to_jupyter = True
            plot.jupyter_args = kwargs
        else:
            print(
                "ERROR: setoutput('jupyter') was set, but we are not in a Jupyter environment"
            )
            raise (Exception("Could not set output to jupyter"))
    else:
        plot.plot_to_jupyter = False
        met_setoutput(*args)


# -----------------------------------------------------------------------------
#                        Other user-visible utiliy functions
# -----------------------------------------------------------------------------


def download_gallery_data(filename):
    base_url = "http://download.ecmwf.org/test-data/metview/gallery/"
    try:
        d = download(url=base_url + filename, target=filename)
        return d
    except:
        raise Exception(
            "Could not download file " + filename + " from the download server"
        )
