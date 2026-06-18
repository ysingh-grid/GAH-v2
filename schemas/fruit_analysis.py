from pydantic import BaseModel
from typing import Dict, Optional, List

class FruitAnalysisItem(BaseModel):
    fruit: str
    a_count: int
    name_length: int
    vowel_count: Optional[int] = None
    tools_used: Dict[str, Optional[str]]
    mcp_tools_used: List[str]
    file_preview: str
