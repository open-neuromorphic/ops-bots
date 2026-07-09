from pydantic import BaseModel, RootModel, ConfigDict
from typing import Dict, List, Any, Union

class TaxonomyItem(BaseModel):
    name: str
    description: str | None = None
    model_config = ConfigDict(extra="allow")

class TaxonomyFile(RootModel):
    """
    Dynamically models Hugo taxonomy JSON structures.
    Accepts lists of strings, lists of item objects, or dictionaries to provide
    flexible schema validation and normalization before feeding the LLM.
    """
    root: Union[List[str], List[TaxonomyItem], Dict[str, Any]]