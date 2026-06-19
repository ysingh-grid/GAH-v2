from pydantic import BaseModel, Field, field_validator
from typing import List, Literal

class CADGenerationResult(BaseModel):
    design_name: str
    js_file_path: str = Field(pattern=r"^outputs/[a-zA-Z0-9_-]+/model\.forge\.js$")
    stl_file_path: str = Field(pattern=r"^outputs/[a-zA-Z0-9_-]+/model\.stl$")
    success: Literal[True]
    compilation_logs: str

    @field_validator("compilation_logs")
    @classmethod
    def validate_compilation_logs(cls, v: str) -> str:
        if "error" in v.lower() or "failed" in v.lower() or "exit code" in v:
            raise ValueError("Compilation logs contain error messages or indicate failure! You MUST fix the .forge.js script syntax and re-compile it until it compiles with 100% success and no errors.")
        return v

class CADGenerationContainer(BaseModel):
    results: List[CADGenerationResult] = Field(min_length=1)






