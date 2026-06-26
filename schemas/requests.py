"""Pydantic schemas for API request/response validation."""
from pydantic import BaseModel, Field
from typing import Optional


# ---- Auth ----
class LoginRequest(BaseModel):
    password: str

class LoginResponse(BaseModel):
    token: str
    message: str = "Login successful"

class PasswordUpdateRequest(BaseModel):
    current_password: str
    new_password: str


# ---- Scripts ----
class ScriptCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: str = ""
    repeat_count: int = Field(default=1, ge=1, le=999)
    delay_between_ms: int = Field(default=1000, ge=0, le=60000)

class ScriptUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = None
    repeat_count: Optional[int] = Field(None, ge=1, le=999)
    delay_between_ms: Optional[int] = Field(None, ge=0, le=60000)


# ---- Actions ----
class ActionCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    action_type: str = Field(..., pattern=r"^(tap|swipe|long_press|screenshot_match|wait|push_key|combo|fetch_api|variable|type_text)$")
    # coords
    x: Optional[float] = None
    y: Optional[float] = None
    x2: Optional[float] = None
    y2: Optional[float] = None
    duration_ms: int = 300
    # screenshot match
    template_path: str = ""
    template_path2: str = ""
    match_threshold: float = 0.80
    retry_count: int = 1
    retry_delay_ms: int = 1000
    jump_on_success: str = ""
    jump_on_fail: str = ""
    # push key
    key_code: str = "HOME"
    # combo
    combo_action: str = "select_all"
    # fetch api
    api_url: str = ""
    api_method: str = "GET"
    api_headers: str = "{}"
    api_body: str = ""
    api_save_to_var: str = ""
    # variable
    var_name: str = ""
    var_operation: str = "set"
    var_value: str = ""
    # type text
    text_content: str = ""
    text_speed_ms: int = 50
    # common
    use_match_result: bool = False
    wait_ms: int = 1000
    wait_before_ms: int = 500
    wait_after_ms: int = 500


class ActionUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=80)
    action_type: Optional[str] = None
    x: Optional[float] = None
    y: Optional[float] = None
    x2: Optional[float] = None
    y2: Optional[float] = None
    duration_ms: Optional[int] = None
    template_path: Optional[str] = None
    template_path2: Optional[str] = None
    match_threshold: Optional[float] = None
    retry_count: Optional[int] = None
    retry_delay_ms: Optional[int] = None
    jump_on_success: Optional[str] = None
    jump_on_fail: Optional[str] = None
    key_code: Optional[str] = None
    combo_action: Optional[str] = None
    api_url: Optional[str] = None
    api_method: Optional[str] = None
    api_headers: Optional[str] = None
    api_body: Optional[str] = None
    api_save_to_var: Optional[str] = None
    var_name: Optional[str] = None
    var_operation: Optional[str] = None
    var_value: Optional[str] = None
    text_content: Optional[str] = None
    text_speed_ms: Optional[int] = None
    use_match_result: Optional[bool] = None
    wait_ms: Optional[int] = None
    wait_before_ms: Optional[int] = None
    wait_after_ms: Optional[int] = None

class ActionReorderRequest(BaseModel):
    order: list[int] = Field(..., description="List of action IDs in desired order")
