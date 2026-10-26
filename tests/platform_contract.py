"""Validate against the downloaded platform OpenAPI, not upstream tau2 assumptions."""
import json
from pathlib import Path
import re
from urllib.parse import unquote

from jsonschema import Draft202012Validator

CONTRACT=json.loads((Path(__file__).resolve().parents[1]/"materials/client_api/openapi.yaml").read_text(encoding="utf-8"))


def validate(schema,value):
    Draft202012Validator({**schema,"components":CONTRACT["components"]}).validate(value)


def operation(request):
    for path,methods in CONTRACT["paths"].items():
        pattern=re.sub(r"\{([^}]+)\}",r"(?P<\1>[^/]+)",path)
        match=re.fullmatch(pattern,request["path"])
        if match and request["method"].lower() in methods:
            method=methods[request["method"].lower()]
            for parameter in method.get("parameters",[]):
                if parameter["in"]=="path":
                    validate(parameter["schema"],unquote(match[parameter["name"]]))
            return path,method
    raise AssertionError("Request is not in the platform's downloaded OpenAPI")


def validate_request(request):
    path,method=operation(request)
    body=method.get("requestBody")
    if body:
        validate(body["content"]["application/json"]["schema"],request.get("body"))
    elif request.get("body") is not None:
        raise AssertionError("This platform operation has no request body")
    allowed_query={p["name"] for p in method.get("parameters",[]) if p["in"]=="query"}
    if set(request.get("query") or {})-allowed_query:
        raise AssertionError("Unexpected platform query parameter")
    return path


def validate_response(request,response):
    _,method=operation(request)
    declaration=method["responses"].get(str(response["status_code"]))
    if declaration is None:
        raise AssertionError("Response status is not documented by the platform")
    content=declaration.get("content",{}).get("application/json")
    if content:
        validate(content["schema"],response["body"])
