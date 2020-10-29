# encoding=utf-8
from abc import ABCMeta
from collections.abc import Sequence
from enum import Enum
from typing import Iterable, Mapping, MutableMapping, Optional, Union
from xml.etree import ElementTree as et  # nosec - We are creating, not parsing XML.

from furl import furl

from mbtest.imposters.base import JsonSerializable, JsonStructure
from mbtest.imposters.behaviors import Copy, Lookup
from mbtest.imposters.predicates import Predicate


class BaseResponse(JsonSerializable, metaclass=ABCMeta):
    @staticmethod
    def from_structure(structure: JsonStructure) -> "BaseResponse":
        if "is" in structure and "_behaviors" in structure:
            return Response.from_structure(structure)
        elif "is" in structure and "data" in structure["is"]:
            return TcpResponse.from_structure(structure)
        elif "proxy" in structure:
            return Proxy.from_structure(structure)
        elif "inject" in structure:
            return InjectionResponse.from_structure(structure)
        raise NotImplementedError()  # pragma: no cover


class Response(BaseResponse):
    """Represents a `Mountebank 'is' response behavior <http://www.mbtest.org/docs/api/stubs>`_.

    :param body: Body text for response. Can be a string, or a JSON serialisable data structure.
    :param status_code: HTTP status code
    :param wait: `Add latency, in ms <http://www.mbtest.org/docs/api/behaviors#behavior-wait>`_.
    :param repeat: `Repeat this many times before moving on to next response
        <http://www.mbtest.org/docs/api/behaviors#behavior-repeat>`_.
    :param headers: Response HTTP headers
    :param mode: Mode - text or binary
    :param copy: Copy behavior
    :param decorate: `Decorate behavior <http://www.mbtest.org/docs/api/behaviors#behavior-decorate>`_.
    :param lookup: Lookup behavior
    :param shell_transform: shellTransform behavior
    """

    class Mode(Enum):
        TEXT = "text"
        BINARY = "binary"

    def __init__(
        self,
        body: str = "",
        status_code: Union[int, str] = 200,
        wait: Optional[Union[int, str]] = None,
        repeat: Optional[int] = None,
        headers: Optional[Mapping[str, str]] = None,
        mode: Optional[Mode] = None,
        copy: Optional[Copy] = None,
        decorate: Optional[str] = None,
        lookup: Optional[Lookup] = None,
        shell_transform: Optional[Union[str, Iterable[str]]] = None,
    ) -> None:
        self._body = body
        self.status_code = status_code
        self.wait = wait
        self.repeat = repeat
        self.headers = headers
        self.mode = (
            mode
            if isinstance(mode, Response.Mode)
            else Response.Mode(mode)
            if mode
            else Response.Mode.TEXT
        )
        self.copy = copy if isinstance(copy, Sequence) else [copy] if copy else None
        self.decorate = decorate
        self.lookup = lookup if isinstance(lookup, Sequence) else [lookup] if lookup else None
        self.shell_transform = shell_transform

    @property
    def body(self) -> str:
        if isinstance(self._body, et.Element):
            return et.tostring(self._body, encoding="unicode")
        elif isinstance(self._body, bytes):
            return self._body.decode("utf-8")
        return self._body

    def as_structure(self) -> JsonStructure:
        return {"is": (self._is_structure()), "_behaviors": self._behaviors_structure()}

    def _is_structure(self) -> JsonStructure:
        is_structure = {"statusCode": self.status_code, "_mode": self.mode.value}
        self._add_if_true(is_structure, "body", self.body)
        self._add_if_true(is_structure, "headers", self.headers)
        return is_structure

    def _behaviors_structure(self) -> JsonStructure:
        behaviors: JsonStructure = {}
        self._add_if_true(behaviors, "wait", self.wait)
        self._add_if_true(behaviors, "repeat", self.repeat)
        self._add_if_true(behaviors, "decorate", self.decorate)
        self._add_if_true(behaviors, "shellTransform", self.shell_transform)
        if self.copy:
            behaviors["copy"] = [c.as_structure() for c in self.copy]
        if self.lookup:
            behaviors["lookup"] = [lookup.as_structure() for lookup in self.lookup]
        return behaviors

    @staticmethod
    def from_structure(structure: JsonStructure) -> "Response":
        response = Response()
        response._fields_from_structure(structure)
        behaviors = structure.get("_behaviors", {})
        response._set_if_in_dict(behaviors, "wait", "wait")
        response._set_if_in_dict(behaviors, "repeat", "repeat")
        response._set_if_in_dict(behaviors, "decorate", "decorate")
        response._set_if_in_dict(behaviors, "shellTransform", "shell_transform")
        if "copy" in behaviors:
            response.copy = [Copy.from_structure(c) for c in behaviors["copy"]]
        if "lookup" in behaviors:
            response.lookup = [Lookup.from_structure(lookup) for lookup in behaviors["lookup"]]
        return response

    def _fields_from_structure(self, structure: JsonStructure) -> None:
        inner = structure["is"]
        if "body" in inner:
            self._body = inner["body"]
        self.mode = Response.Mode(inner["_mode"])
        if "headers" in inner:
            self.headers = inner["headers"]
        if "statusCode" in inner:
            self.status_code = inner["statusCode"]


class TcpResponse(BaseResponse):
    def __init__(self, data: str) -> None:
        self.data = data

    def as_structure(self) -> JsonStructure:
        return {"is": {"data": self.data}}

    @staticmethod
    def from_structure(structure: JsonStructure) -> "TcpResponse":
        return TcpResponse(data=structure["is"]["data"])


class Proxy(BaseResponse):
    """Represents a `Mountebank proxy <http://www.mbtest.org/docs/api/proxies>`_.

    :param to: The origin server, to which the request should proxy.
    """

    class Mode(Enum):
        """Defines the replay behavior of the proxy."""

        ONCE = "proxyOnce"
        ALWAYS = "proxyAlways"
        TRANSPARENT = "proxyTransparent"

    def __init__(
        self,
        to: Union[furl, str],
        wait: Optional[int] = None,
        inject_headers: Optional[Mapping[str, str]] = None,
        mode: "Proxy.Mode" = Mode.ONCE,
        predicate_generators: Optional[Iterable["PredicateGenerator"]] = None,
    ) -> None:
        self.to = to
        self.wait = wait
        self.inject_headers = inject_headers
        self.mode = mode
        self.predicate_generators = predicate_generators if predicate_generators is not None else []

    def as_structure(self) -> JsonStructure:
        proxy = {
            "to": self.to.url if isinstance(self.to, furl) else self.to,
            "mode": self.mode.value,
        }
        self._add_if_true(proxy, "injectHeaders", self.inject_headers)
        self._add_if_true(
            proxy, "predicateGenerators", [pg.as_structure() for pg in self.predicate_generators]
        )
        response = {"proxy": proxy}
        if self.wait:
            response["_behaviors"] = {"wait": self.wait}
        return response

    @staticmethod
    def from_structure(structure: JsonStructure) -> "Proxy":
        proxy_structure = structure["proxy"]
        proxy = Proxy(
            to=furl(proxy_structure["to"]),
            inject_headers=proxy_structure["injectHeaders"]
            if "injectHeaders" in proxy_structure
            else None,
            mode=Proxy.Mode(proxy_structure["mode"]),
            predicate_generators=[
                PredicateGenerator.from_structure(pg)
                for pg in proxy_structure["predicateGenerators"]
            ]
            if "predicateGenerators" in proxy_structure
            else None,
        )
        wait = structure.get("_behaviors", {}).get("wait")
        if wait:
            proxy.wait = wait
        return proxy


class PredicateGenerator(JsonSerializable):
    def __init__(
        self,
        path: bool = False,
        query: Union[bool, Mapping[str, str]] = False,
        operator: Predicate.Operator = Predicate.Operator.EQUALS,
        case_sensitive: bool = True,
    ):
        self.path = path
        self.query = query
        self.operator = operator
        self.case_sensitive = case_sensitive

    def as_structure(self) -> JsonStructure:
        matches: MutableMapping[str, str] = {}
        self._add_if_true(matches, "path", self.path)
        self._add_if_true(matches, "query", self.query)
        predicate = {"caseSensitive": self.case_sensitive, "matches": matches}
        return predicate

    @staticmethod
    def from_structure(structure: JsonStructure) -> "PredicateGenerator":
        path = structure["matches"].get("path", None)
        query = structure["matches"].get("query", None)
        operator = (
            Predicate.Operator[structure["operator"]]
            if "operator" in structure
            else Predicate.Operator.EQUALS
        )
        case_sensitive = structure.get("caseSensitive", False)
        return PredicateGenerator(
            path=path, query=query, operator=operator, case_sensitive=case_sensitive
        )


class InjectionResponse(BaseResponse):
    """Represents a `Mountebank injection response <http://www.mbtest.org/docs/api/injection>`_.

    Injection requires Mountebank version 2.0 or higher.

    :param inject: JavaScript function to inject .
    """

    def __init__(self, inject: str) -> None:
        self.inject = inject

    def as_structure(self) -> JsonStructure:
        return {"inject": self.inject}

    @staticmethod
    def from_structure(structure: JsonStructure) -> "InjectionResponse":
        return InjectionResponse(inject=structure["inject"])
