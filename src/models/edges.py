from pydantic import BaseModel


class ImportEdge(BaseModel):
    source_module: str
    target_module: str
    import_count: int = 1


class ProducesEdge(BaseModel):
    transformation: str
    dataset: str
    source_file: str = ""
    line_range: tuple[int, int] = (0, 0)


class ConsumesEdge(BaseModel):
    transformation: str
    dataset: str
    source_file: str = ""
    line_range: tuple[int, int] = (0, 0)


class CallsEdge(BaseModel):
    caller: str
    callee: str


class ConfiguresEdge(BaseModel):
    config_file: str
    target: str
