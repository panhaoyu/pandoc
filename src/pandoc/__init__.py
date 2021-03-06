# coding: utf-8

# Python 3 Standard Library
import argparse
import collections
import copy
import inspect
import json
import os.path
import shlex
import shutil
import sys
import time
import tempfile

# Third-Party Libraries
import plumbum

# Pandoc
import pandoc.about
from . import utils

# TODO
# ------------------------------------------------------------------------------
#
#   - Add pandoc options to the CLI (use shlex or partial parsing in argparse ?)
#

# Filesystem Helper
# ------------------------------------------------------------------------------
def rmtree(path):
    """Deal with Windows 
    (see e.g <https://www.gitmemory.com/issue/sdispater/poetry/1031/488759621>
    """
    retries = 10
    for i in range(retries - 1):
        try:
            shutil.rmtree(path)
            return
        except OSError:
            time.sleep(0.1)
    shutil.rmtree(path)


# Configuration
# ------------------------------------------------------------------------------
_configuration = None


def import_types():
    if configure(read=True) is None:
        configure(auto=True)
    import pandoc.types as types

    return types


def configure(
    auto=None,
    path=None,
    version=None,
    pandoc_types_version=None,
    read=False,
    reset=False,
):
    global _configuration

    default = (
        auto is None
        and path is None
        and version is None
        and pandoc_types_version is None
        and read is False
        and reset is False
    )
    if default:
        error = "configure expects at least one argument."
        raise ValueError(error)

    if reset is True:
        _configuration = None  # TODO: clean the types
        return

    read_only = (
        read
        and auto is None
        and path is None
        and version is None
        and pandoc_types_version is None
    )

    if auto:
        try:
            pandoc = plumbum.local["pandoc"]
            found_path = str(pandoc.executable)
        except plumbum.CommandNotFound as error:
            message = "cannot find the pandoc program.\n"
            paths = [str(p) for p in error.path]
            message += "paths:" + str(paths)
            raise RuntimeError(message)
        if path is None:
            path = found_path
        elif path != found_path:
            error = "found path {0!r} with auto=True "
            error += "but it doesn't match path={1!r}."
            raise ValueError(error.format(found_path, path))

    if path is not None:
        # TODO: manage invalid path
        pandoc = plumbum.machines.LocalCommand(path, "utf-8")
        found_version = pandoc("--version").splitlines()[0].split(" ")[1]
        if version is None:
            version = found_version
        elif version != found_version:
            error = "the version of the pandoc program is {0!r}"
            error += "but it doesn't match version={1!r}."
            raise ValueError(error.format(found_version, version))

    if version is not None:
        found_pandoc_types_versions = utils.resolve(version)
        if pandoc_types_version is None:
            if len(found_pandoc_types_versions) >= 1:
                # pick latest (ignore the real one that may be unknown)
                pandoc_types_version = found_pandoc_types_versions[-1]
            else:
                error = "cannot find a version of pandoc-types "
                error += "matching pandoc {0}"
                raise ValueError(error.format(version))
        elif pandoc_types_version not in found_pandoc_types_versions:
            error = "the version of pandoc is {0!r}"
            error += "but it doesn't match pandoc_types_version={1!r}."
            raise ValueError(error.format(version, pandoc_types_version))

    if not read_only:  # set the configuration, update pandoc.types

        try:
            from . import types
        except ImportError:  # only sensible explanation:
            # the types module is actually being imported (interpreted)
            # and is calling configure.
            types = sys.modules["pandoc.types"]

        _configuration = {
            "auto": auto,
            "path": path,
            "version": version,
            "pandoc_types_version": pandoc_types_version,
        }

        types.make_types()

    if read:
        return copy.copy(_configuration)


# JSON Reader / Writer
# ------------------------------------------------------------------------------

# Break compat? Read consumes markdown only? Bump major version number then.
# Yay, worth it.
#
# TODO: optional input or output FILES or FILENAMES in read/write? Dunno.
#       Think about it. The NAMES read and write seem to imply it ...
#       But the filesystem stuff is orthogonal really ...
#       However, for a ".doc" output for example, writing it as a string
#       is *probably* useless.
#
# TODO: Study also the str vs bytes stuff: we don't want encoding stuff
#       mixed in when we produce a word document, just BYTES.
#       For Markdown OTOH, unicode repr is the right abstraction.
#       What to do for latex, html docs? Bytes or Unicode?
#       FYI, Pandoc is using DECLARING utf-8 encoding for both in standalone
#       mode, so if you write these standalone outputs, you SHALL use utf-8 ...
#       Otherwise, well, I don't know ... but it's pretty much the same for
#       markdown: to get it properly processed, pandoc REQUIRES utf-8.
#       So, distinguish, markdown, latex and html as "source formats" and
#       use unicode for them? And bytes for the others?
#       What is the list? There is also ReST? How to get it automatically?
#       Try to trap the error? (Assuming the error message are stable?)
#       Nota: from the pandoc source code, ATM, "non-text formats" are
#        ["odt","docx","epub2","epub3","epub","pptx"]
#       But the non-text format categorization is used for OUTPUTS only,
#       what about inputs? OK, there is a classification into StringReader
#       (text sources) and ByteStringReader. For the latter, piping is not
#       accepted. So where is the list of the types of readers?
#       Grepping the sources leads to "docx", "odt" and "epub". OK then.
#       Am I really willing to hardcode all this stuff, or shall I return
#       bytes and let the user decide what to do with it? For INPUTS,
#       I can still accept unicode and convert to utf-8 seemlessly, the
#       question is: what to do for outputs? Only return unicode for markdown?
#       (that has no encoding metadata)? Dunno ...
#       UPDATE: OK, I have configured plumbum to always use utf-8 when
#       there is some conversion to be made between unicode and bytes.
#       BUT how can I deal with stuff (in or out) that are BYTES that
#       may not be utf-8 stuff?
#       Also, I forgot to configure cat for utf-8 ... and is cat available
#       on windows? Use temp files instead, that will solve two issues at
#       the same time (bytes as input and car availability).
#       Arf for the output, this is funny: for docx for example,
#       pandoc (haskell) WONT LET ME USE STDOUT! Which is nice :)
#       Nota: it won't read it either; so basically it manages differently
#       the binary formats. Same thing for epub for examples.
#       The messages are typically "pandoc: Cannot read archive from stdin"
#       and "Specify an output file using the -o option".
#       So I have to find a list in pandoc of binary vs text/utf-8 formats.
#       OR detect the appropriate error at runtime?
#       And then the bytes vs unicode policy is clear.
#       And I don't need to tweak encoding settings in plumbum since I
#       will use files for input and output anyway.
#
#       OK, so it's probaly safe to consider a shortlist of "binary" formats
#       that are "doc*", "epub*", "ppt*", "odt" and to return bytes only
#       for these formats.
#
#       And yes, working directly with filenames/files should work out
#       of the box, and yes, NOT using files should be ok too (and is
#       still my preferences: it should be simpler; if you need files,
#       use a proper keyword argument).

# TODO: add ".py" / Python support

_readers = {
    ".xhtml": "html",
    ".html": "html",
    ".htm": "html",
    ".md": "markdown",
    ".markdown": "markdown",
    ".muse": "muse",
    ".tex": "latex",
    ".latex": "latex",
    ".ltx": "latex",
    ".rst": "rst",
    ".org": "org",
    ".lhs": "markdown+lhs",
    ".db": "docbook",
    ".opml": "opml",
    ".wiki": "mediawiki",
    ".dokuwiki": "dokuwiki",
    ".textile": "textile",
    ".native": "native",
    ".json": "json",
    ".docx": "docx",
    ".t2t": "t2t",
    ".epub": "epub",
    ".odt": "odt",
    ".pdf": "pdf",
    ".doc": "doc",
}


def default_reader_name(filename):
    _, ext = os.path.splitext(filename)
    return _readers.get(ext)


def read(source=None, file=None, format=None, options=None):
    if configure(read=True) is None:
        configure(auto=True)
    if options is None:
        options = []

    filename = None
    if source is None:
        if file is None:
            raise ValueError("source or file should be defined.")
        if not hasattr(file, "read"):
            filename = file
            file = open(filename, "rb")
        source = file.read()
    else:
        if file is not None:
            raise ValueError("source or file should be defined, not both.")

    tmp_dir = tempfile.mkdtemp()
    if not isinstance(source, bytes):
        source = source.encode("utf-8")
    input_path = os.path.join(tmp_dir, "input")
    input = open(input_path, "wb")
    input.write(source)
    input.close()

    if format is None and filename is not None:
        format = default_reader_name(filename)
    if format is None:
        format = "markdown"
    if format != "json" and _configuration["path"] is None:
        error = "reading the {0!r} format requires the pandoc program"
        raise RuntimeError(error.format(format))

    if format == "json":
        json_file = open(input_path, "r", encoding="utf-8")
    else:
        if _configuration["path"] is None:
            error = "reading the {0!r} format requires the pandoc program"
            raise RuntimeError(error.format(format))
        pandoc = plumbum.machines.LocalCommand(_configuration["path"])
        output_path = os.path.join(tmp_dir, "output.js")
        options = (
            ["-t", "json", "-o", output_path]
            + list(options)
            + ["-f", format, input_path]
        )
        pandoc(options)
        json_file = open(output_path, "r", encoding="utf-8")
    json_ = json.load(json_file)
    json_file.close()
    rmtree(tmp_dir)
    if utils.version_key(_configuration["pandoc_types_version"]) < [1, 17]:
        return read_json_v1(json_)
    else:
        return read_json_v2(json_)


# TODO: add ".py" / Python support

_writers = {
    "": "markdown",
    ".pdf": "latex",
    ".tex": "latex",
    ".latex": "latex",
    ".ltx": "latex",
    ".context": "context",
    ".ctx": "context",
    ".rtf": "rtf",
    ".rst": "rst",
    ".s5": "s5",
    ".native": "native",
    ".json": "json",
    ".txt": "markdown",
    ".text": "markdown",
    ".md": "markdown",
    ".muse": "muse",
    ".markdown": "markdown",
    ".textile": "textile",
    ".lhs": "markdown+lhs",
    ".texi": "texinfo",
    ".texinfo": "texinfo",
    ".db": "docbook",
    ".odt": "odt",
    ".docx": "docx",
    ".epub": "epub",
    ".org": "org",
    ".asciidoc": "asciidoc",
    ".adoc": "asciidoc",
    ".fb2": "fb2",
    ".opml": "opml",
    ".icml": "icml",
    ".tei.xml": "tei",
    ".tei": "tei",
    ".ms": "ms",
    ".roff": "ms",
    ".pptx": "pptx",
    ".xhtml": "html",
    ".html": "html",
    ".htm": "html",
}


def default_writer_name(filename):
    if filename.endswith(".tei.xml"):
        filename = filename[:-4]  # uhu ? test this.
    _, ext = os.path.splitext(filename)
    if len(ext) == 2 and ext[1] in "0123456789":
        return "man"
    else:
        return _writers.get(ext)


# TODO: better management for pdf "format" which is not a format according
#       to pandoc ... ("latex" or "beamer" are, pdf is hidden in the filename
#       extension)


def write(doc, file=None, format=None, options=None):
    if options is None:
        options = []

    types = import_types()

    if isinstance(doc, types.Inline):
        inline = doc
        doc = [inline]
    if isinstance(doc, list) and all(isinstance(elt, types.Inline) for elt in doc):
        inlines = doc
        doc = types.Plain(inlines)
    if isinstance(doc, types.Block):
        block = doc
        doc = [block]
    if isinstance(doc, list) and all(isinstance(elt, types.Block) for elt in doc):
        blocks = doc
        doc = types.Pandoc(types.Meta({}), blocks)
    if not isinstance(doc, types.Pandoc):
        raise TypeError(f"{doc!r} is not a Pandoc, Block or Inline instance.")

    tmp_dir = tempfile.mkdtemp()
    filename = None
    if file is not None and not hasattr(file, "write"):
        filename = file
        file = open(filename, "wb")

    if format is None and filename is not None:
        format = default_writer_name(filename)
    if format is None:
        format = "markdown"  # instead of html, yep.
    if format != "json" and _configuration["path"] is None:
        error = "writing the {0!r} format requires the pandoc program"

    configuration = configure(read=True)
    if utils.version_key(configuration["pandoc_types_version"]) < [1, 17]:
        json_ = write_json_v1(doc)
    else:
        json_ = write_json_v2(doc)
    json_str = json.dumps(json_)
    input_path = os.path.join(tmp_dir, "input.js")
    input = open(input_path, "wb")
    input.write(json_str.encode("utf-8"))
    input.close()

    if format == "json":
        output_path = input_path
    else:
        if filename is not None:
            # preserve extensions (sometimes pandoc looks for the extension,
            # e.g. for pdf files)
            tmp_filename = os.path.basename(filename)
        else:
            tmp_filename = "output"
        pandoc = plumbum.machines.LocalCommand(_configuration["path"])
        output_path = os.path.join(tmp_dir, tmp_filename)
        options = (
            ["-t", format, "-o", output_path]
            + list(options)
            + ["-f", "json", input_path]
        )
        pandoc(options)

    output_bytes = open(output_path, "rb").read()
    binary_formats = ["doc", "epub", "ppt", "odt"]
    if any(tag in format for tag in binary_formats) or output_path.endswith(".pdf"):
        output = output_bytes
    else:  # text format
        output = output_bytes.decode("utf-8")
    rmtree(tmp_dir)

    if file is not None:
        file.write(output_bytes)
    return output


# JSON Reader v1
# ------------------------------------------------------------------------------
def read_json_v1(json_, type_=None):
    types = import_types

    if type_ is None:
        type_ = types.Pandoc
    if isinstance(type_, str):
        type_ = getattr(types, type_)
    if not isinstance(type_, list):  # not a type def (yet).
        if issubclass(type_, types.Type):
            type_ = type_._def
        else:  # primitive type
            return type_(json_)

    if type_[0] == "type":  # type alias
        type_ = type_[1][1]
        return read_json_v1(json_, type_)
    if type_[0] == "list":
        item_type = type_[1][0]
        return [read_json_v1(item, item_type) for item in json_]
    if type_[0] == "tuple":
        tuple_types = type_[1]
        return tuple(
            read_json_v1(item, item_type)
            for (item, item_type) in zip(json_, tuple_types)
        )
    if type_[0] == "map":
        key_type, value_type = type_[1]
        return types.map(
            [
                (read_json_v1(k, key_type), read_json_v1(v, value_type))
                for (k, v) in json_.items()
            ]
        )

    data_type = None
    constructor = None
    if type_[0] in ("data", "newtype"):
        data_type = type_
        constructors = data_type[1][1]
        if len(constructors) == 1:
            constructor = constructors[0]
        else:
            constructor = getattr(types, json_["t"])._def
    elif type_[0][0] == type_[0][0].upper():
        constructor = type_
        constructor_type = getattr(types, constructor[0])
        data_type = constructor_type.__mro__[2]._def

    single_type_constructor = len(data_type[1][1]) == 1
    single_constructor_argument = len(constructor[1][1]) == 1
    is_record = constructor[1][0] == "map"

    json_args = None
    args = None
    if not is_record:
        if single_type_constructor:
            json_args = json_
        else:
            json_args = json_["c"]
        if single_constructor_argument:
            json_args = [json_args]
        args = [read_json_v1(jarg, t) for jarg, t in zip(json_args, constructor[1][1])]
    else:
        keys = [k for k, t in constructor[1][1]]
        types_ = [t for k, t in constructor[1][1]]
        json_args = [json_[k] for k in keys]
        args = [read_json_v1(jarg, t) for jarg, t in zip(json_args, types_)]
    C = getattr(types, constructor[0])
    return C(*args)


# JSON Writer v1
# ------------------------------------------------------------------------------
def write_json_v1(object_):
    types = import_types()

    odict = collections.OrderedDict
    type_ = type(object_)
    if not isinstance(object_, types.Type):
        if isinstance(object_, (list, tuple)):
            json_ = [write_json_v1(item) for item in object_]
        elif isinstance(object_, dict):
            json_ = odict((k, write_json_v1(v)) for k, v in object_.items())
        else:  # primitive type
            json_ = object_
    else:
        constructor = type(object_)._def
        data_type = type(object_).__mro__[2]._def
        single_type_constructor = len(data_type[1][1]) == 1
        single_constructor_argument = len(constructor[1][1]) == 1
        is_record = constructor[1][0] == "map"

        json_ = odict()
        if not single_type_constructor:
            json_["t"] = type(object_).__name__

        if not is_record:
            c = [write_json_v1(arg) for arg in object_]
            if single_constructor_argument:
                c = c[0]
            if single_type_constructor:
                json_ = c
            else:
                json_["c"] = c
        else:
            keys = [kt[0] for kt in constructor[1][1]]
            for key, arg in zip(keys, object_):
                json_[key] = write_json_v1(arg)
    return json_


# JSON Reader v2
# ------------------------------------------------------------------------------
def read_json_v2(json_, type_=None):
    # DEBUG needed. Maybe in Caption makes the process go wrong.
    #print("type:", type_, "json:", json_)
    types = import_types()

    if type_ is None:
        type_ = types.Pandoc
    if isinstance(type_, str):
        type_ = getattr(types, type_)
    if not isinstance(type_, list):  # not a type def (yet).
        if issubclass(type_, types.Type):
            type_ = type_._def
        else:  # primitive type
            return type_(json_)

    #print("typedef:", type_)


    if type_[0] == "type":  # type alias
        type_ = type_[1][1]
        return read_json_v2(json_, type_)
    if type_[0] == "list":
        item_type = type_[1][0]
        return [read_json_v2(item, item_type) for item in json_]
    if type_[0] == "tuple":
        tuple_types = type_[1]
        return tuple(
            read_json_v2(item, item_type)
            for (item, item_type) in zip(json_, tuple_types)
        )
    if type_[0] == "map":
        key_type, value_type = type_[1]
        return types.map(
            [
                (read_json_v2(k, key_type), read_json_v2(v, value_type))
                for (k, v) in json_.items()
            ]
        )
    if type_[0] == "maybe":
        value_type = type_[1][0]
        if json_ == None:
            return None
        else:
            return read_json_v2(json_, value_type)

    data_type = None
    constructor = None
    if type_[0] in ("data", "newtype"):
        data_type = type_
        constructors = data_type[1][1]
        if len(constructors) == 1:
            constructor = constructors[0]
        else:
            #print("*", json_)
            constructor = getattr(types, json_["t"])._def
    elif type_[0][0] == type_[0][0].upper():
        constructor = type_
        constructor_type = getattr(types, constructor[0])
        data_type = constructor_type.__mro__[2]._def

    single_type_constructor = len(data_type[1][1]) == 1
    single_constructor_argument = len(constructor[1][1]) == 1
    is_record = constructor[1][0] == "map"

    json_args = None
    args = None
    if constructor[0] == "Pandoc":
        # TODO; check API version compat
        meta = read_json_v2(json_["meta"], types.Meta)
        blocks = read_json_v2(json_["blocks"], ["list", ["Block"]])
        return types.Pandoc(meta, blocks)
    elif constructor[0] == "Meta":
        type_ = ["map", ["String", "MetaValue"]]
        return types.Meta(read_json_v2(json_, type_))
    elif not is_record:
        if single_type_constructor:
            # For some reason, "Caption", which has a single constructor,
            # does not erase the type ? Is it an issue of being a "newtype"
            # and not a "data". That would make sense based on the semantics
            # of these words. Let's experiment now :
            # newtype instances are Meta (special case), Format, RowHeadColumns,
            # RowSpan and ColSpan. Well with pandoc 2.10.1, this intuition is
            # wrong: RowSpan and ColSpan have their types in the json at least.
            # Format has its type erased. RowHeadColumns types is not erased either.
            # So now it's only Format (and Meta) ??? Why ? And where can I see this
            # in the code ? 
            # data with single constructor: Row, TableHead, TableBody, TableFoot,
            # Cell, etc.

            # NOTE : also new: ColWidth has a constructor named ColWidth,
            #        but there is also a default ; so we can't read hide
            #        the father type, safely can we ?

            json_args = json_
        else:
            json_args = json_.get("c", [])
        if single_constructor_argument:
            json_args = [json_args]
        args = [read_json_v2(jarg, t) for jarg, t in zip(json_args, constructor[1][1])]
    else:
        keys = [k for k, t in constructor[1][1]]
        types_ = [t for k, t in constructor[1][1]]
        json_args = [json_[k] for k in keys]
        args = [read_json_v2(jarg, t) for jarg, t in zip(json_args, types_)]
    C = getattr(types, constructor[0])
    return C(*args)


# JSON Writer v2
# ------------------------------------------------------------------------------
def write_json_v2(object_):
    types = import_types()

    odict = collections.OrderedDict
    type_ = type(object_)
    if not isinstance(object_, types.Type):
        if isinstance(object_, (list, tuple)):
            json_ = [write_json_v2(item) for item in object_]
        elif isinstance(object_, dict):
            json_ = odict((k, write_json_v2(v)) for k, v in object_.items())
        else:  # primitive type, (inc. None used by Maybe's)
            json_ = object_
    elif isinstance(object_, types.Pandoc):
        version = configure(read=True)["pandoc_types_version"]
        metadata = object_[0]
        blocks = object_[1]
        json_ = odict()
        json_["pandoc-api-version"] = [int(n) for n in version.split(".")]
        json_["meta"] = write_json_v2(object_[0][0])
        json_["blocks"] = write_json_v2(object_[1])
    else:
        constructor = type(object_)._def
        data_type = type(object_).__mro__[2]._def
        single_type_constructor = len(data_type[1][1]) == 1
        has_constructor_arguments = len(constructor[1][1]) >= 1
        single_constructor_argument = len(constructor[1][1]) == 1
        is_record = constructor[1][0] == "map"

        json_ = odict()
        if not single_type_constructor:
            json_["t"] = type(object_).__name__
        if not is_record:
            c = [write_json_v2(arg) for arg in object_]
            if single_constructor_argument:
                c = c[0]
            if single_type_constructor:
                json_ = c
            else:
                if has_constructor_arguments:
                    json_["c"] = c
        else:
            keys = [kt[0] for kt in constructor[1][1]]
            for key, arg in zip(keys, object_):
                json_[key] = write_json_v2(arg)
    return json_


# Iteration
# ------------------------------------------------------------------------------

# Thoughts:
#
#   - maybe 'iter_path' is not the right naming:
#     I would envision for iter_path something that returns roughly speaking
#     a list of indices that would allow us to find the element from doc.
#     What would be the right new name for the old concept of path then?
#     Have the list of ancestors named "context"? for example?
#     And have it as supplementary data (also return elt as usual?)
#     So consider a "mega-iter-named-whataver-with-options" ?
#     And keep "iter" for the building block? Or use 'iter' for that?
#     Wrt path as list of indices: have [] (or another function) support
#     these list of path directly? Yeah would need some support anyway.
#
#   - Nota: I have at least 3 different "context" structures that may
#     be handy:
#
#       - the list of parents (say without the elt, aka "context" or "parents"?)
#
#       - the list of indices (aka "path")
#
#       - a hybrid parent + index tuple list.
#
#     And these lists *may* (or may not) be reversed for convenience.
#     Actually we may keep the top to bottom order and name "path"
#     the list of pairs. This is a redundant structure (all you need
#     for example is the root and the indices), but we don't care,
#     the redundancy is actually convenient.
#
#     And add a "path" option to iter to return the (elt, path) pair.
#     Does it fly? Name ? "path" or "context"? Nah, path ...
#
#   - Nota: does it make sense to also use string keys in path for maps?
#     Several issues: have a look in the complete chain to see if pandoc
#     map-like structure have their ordered preserved (I think not),
#     then think "tree/structural" vs value stuff (maps have a varying
#     number of items for example ...), and finally think of the consistency
#     of the interface of named keys wrt to "iter" that is 100% integer based.
#     Nota wrt "non-structural iteration": we are already doing it with lists,
#     so nothing new here.
#
#  - TODO: explore visitor-style stuff (have a look at ANTLR for example)
#
#  - TODO: explore functional programming style (e.g. apply for trees, etc.)
#


def iter(elt, path=False, enter=None, exit=None):
    if path is not False:
        if not isinstance(path, list):  # e.g. path = True
            path = []

    args = [elt]
    if path is not False:
        args.append(path)

    if enter is not None:
        enter(*args)

    if path is False:
        yield elt
    else:
        yield elt, path

    if isinstance(elt, dict):
        elt = elt.items()
    if hasattr(elt, "__iter__") and not isinstance(elt, types.String):
        for i, child in enumerate(elt):
            if path is False:
                child_path = False
            else:
                child_path = path.copy() + [(elt, i)]
            for subelt in iter(child, path=child_path, enter=enter, exit=exit):
                yield subelt

    if exit is not None:
        exit(*args)


def iter_path(elt):
    path = []

    def enter(elt_):
        path.append(elt_)

    def exit(elt_):
        path.pop()

    for elt_ in iter(elt, enter=enter, exit=exit):
        yield path

class Symbol(str):
    def __new__(cls, *args, **kw):
        return str.__new__(cls, *args, **kw)
    def __repr__(self):
        return str(self)

ENTER = Symbol("ENTER")
EXIT = Symbol("EXIT")



# class Iter2:
#     def __init__(root, path=None, way=None):
#         if path is None:
#             path = []
#         if way is None:
#             way = ENTER
#         self.root = root
#         self.path = path
#         self.way = way
#     def __iter__(self):
#         return self
#     def __next__(self):
#         if self.way == ENTER:
#             if self.path == []:
#                 return self.root, ENTER
#             else:
#                 parent, index = self.path[-1]
#                 return parent[index], ENTER
            
#             else:
#                 parent, index = self.path[-1]
#                 if not hasattr(parent, "__getitem__") or isinstance(parent, str):
#                     return self.elt, EXIT
#                 if isinstance(parent, dict):
#                     parent = list(parent.items())
#                 try:
#                     elt = parent[index]
#                     self.path.append((elt, 0))
#                 except IndexError:
#                     self.way = EXIT
#                     return parent, EXIT

                


def get_parent(doc, elt):
    for path in iter_path(doc):
        elt_ = path[-1]
        if elt is elt_:
            parent = path[-2] if len(path) >= 2 else None
            return parent


# Functional Transformation Patterns (Scrap-Your-Boilerplate-ish)
# ------------------------------------------------------------------------------
def _apply_children(f, elt):
    types = import_types()
    children = None
    if isinstance(elt, types.Type):
        children = elt[:]
        new_children = [f(child) for child in children]
        return type(elt)(*new_children)
    elif isinstance(elt, dict):
        children = elt.items()
        return dict([f(child) for child in children])
    elif hasattr(elt, "__iter__") and not isinstance(elt, types.String):
        assert isinstance(elt, list) or isinstance(elt, tuple)
        new_children = [f(child) for child in elt]
        return type(elt)(new_children)
    else:
        assert type(elt) in [bool, int, float, str]
        return elt

def apply(f, elt=None): # apply the transform f bottom-up
    f_ = f

    def f(elt): # sugar : no return value means no change 
        new_elt = f_(elt)
        if new_elt is not None:
            return new_elt
        else:
            return elt

    def apply_(f, elt=None):
        if elt is None:  # functional style / decorator
            return lambda elt: apply_(f, elt)

        def apply_descendants(elt):
            return _apply_children(apply_(f), elt)

        return f(apply_descendants(elt))

    return apply_(f, elt)


# Main Entry Point
# ------------------------------------------------------------------------------
# TODO : support custom indendation for Python output.
# BUG : by using files instead of filenames in argparse types,
#       we are losing the extension info and cannot select the proper format.
#       This is an issue in itself ; but since we use the pandoc convention
#       not to have "pdf" as an output format per se, that means that we
#       cannot output pdf at all.
def main():
    prog = "python -m pandoc"
    description = "Read/write pandoc documents with Python"
    parser = argparse.ArgumentParser(prog=prog, description=description)
    parser.set_defaults(command=None)
    subparsers = parser.add_subparsers()
    read_parser = subparsers.add_parser("read")
    read_parser.set_defaults(command="read")
    read_parser.add_argument(
        "file", nargs="?", metavar="FILE", default=None, help="input file"
    )
    read_parser.add_argument(
        "-f", "--format", nargs="?", default=None, help="input format"
    )
    read_parser.add_argument(
        "-o", "--output", nargs="?", default=None, help="output file"
    )
    write_parser = subparsers.add_parser("write")
    write_parser.set_defaults(command="write")
    write_parser.add_argument(
        "file", nargs="?", metavar="FILE", default=None, help="input file"
    )
    write_parser.add_argument(
        "-f", "--format", nargs="?", default=None, help="output format"
    )
    write_parser.add_argument(
        "-o", "--output", nargs="?", default=None, help="output file"
    )
    args = parser.parse_args()
    if args.command == "read":
        if args.file is None:
            file = sys.stdin
        else:
            file = args.file
        doc = read(file=file, format=args.format)
        content = str(doc) + "\n"
        if args.output is None:
            output = sys.stdout.buffer
        else:
            output = open(args.output, "wb")
        assert "b" in output.mode
        content = content.encode("utf-8")
        output.write(content)
    elif args.command == "write":
        if args.file is None:
            # We always interpret the standard input stream as utf-8 ;
            # see <https://pandoc.org/MANUAL.html#character-encoding>
            file = sys.stdin.buffer  # sys.stdin may not be utf-8.
            assert "b" in file.mode
            doc_bytes = file.read()
            doc_string = doc_bytes.decode("utf-8")
        else:
            file = open(args.file, mode="r", encoding="utf-8")
            doc_string = file.read()
        types = import_types()
        globs = types.__dict__.copy()
        doc = eval(doc_string, globs)
        if args.output is None:
            output = sys.stdout.buffer
        else:
            output = args.output
        write(doc, file=output, format=args.format)
