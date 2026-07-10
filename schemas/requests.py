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
    name: str = Field(..., min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_]+$")
    description: str = ""
    repeat_count: int = Field(default=1, ge=1, le=999)
    delay_between_ms: int = Field(default=1000, ge=0, le=60000)
    stop_on_failure: bool = False

class ScriptUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_]+$")
    description: Optional[str] = None
    repeat_count: Optional[int] = Field(None, ge=1, le=999)
    delay_between_ms: Optional[int] = Field(None, ge=0, le=60000)
    stop_on_failure: Optional[bool] = None


# ---- Actions ----
class ActionCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    action_type: str = Field(..., pattern=r"^(tap|swipe|long_press|screenshot_match|wait|push_key|combo|fetch_api|variable|type_text|jump|stop|if|orientation|launch_app|kill_app|read_sms|call_script|goto_script|toast)$")
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
    # match region (crop area on screen before matching)
    match_region_x: Optional[float] = None
    match_region_y: Optional[float] = None
    match_region_w: Optional[float] = None
    match_region_h: Optional[float] = None
    match_region_screen: str = ""
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
    # jump
    jump_to: str = ""
    # stop/kill — no extra fields needed
    # if / condition
    condition_var: str = ""
    condition_op: str = "eq"
    condition_value: str = ""
    jump_on_true: str = ""
    jump_on_false: str = ""
    # orientation
    orientation_value: str = "auto"
    # launch_app / kill_app
    app_package: str = ""
    # call_script / goto_script
    call_script_name: str = ""
    goto_script_name: str = ""
    # toast
    toast_message: str = ""
    toast_duration: str = "short"
    # common
    enabled: bool = True
    use_match_result: bool = False
    wait_ms: int = 1000
    wait_before_ms: int = 500
    wait_after_ms: int = 500
    # keyboard mapping for type_text via tap
    keyboard_mapping_id: Optional[int] = None


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
    match_region_x: Optional[float] = None
    match_region_y: Optional[float] = None
    match_region_w: Optional[float] = None
    match_region_h: Optional[float] = None
    match_region_screen: Optional[str] = None
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
    # jump
    jump_to: Optional[str] = None
    # stop/kill — no extra fields
    # if / condition
    condition_var: Optional[str] = None
    condition_op: Optional[str] = None
    condition_value: Optional[str] = None
    jump_on_true: Optional[str] = None
    jump_on_false: Optional[str] = None
    # orientation
    orientation_value: Optional[str] = None
    # launch_app / kill_app
    app_package: Optional[str] = None
    # call_script / goto_script
    call_script_name: Optional[str] = None
    goto_script_name: Optional[str] = None
    # toast
    toast_message: Optional[str] = None
    toast_duration: Optional[str] = None
    # common
    enabled: Optional[bool] = None
    use_match_result: Optional[bool] = None
    wait_ms: Optional[int] = None
    wait_before_ms: Optional[int] = None
    wait_after_ms: Optional[int] = None
    # keyboard mapping for type_text via tap
    keyboard_mapping_id: Optional[int] = None

class ActionReorderRequest(BaseModel):
    order: list[int] = Field(..., description="List of action IDs in desired order")

# ---- Keyboard Mapping ----
class KeyboardMappingCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    layout_type: str = Field(default="qwerty", pattern=r"^(qwerty|number)$")
    keys_json: dict[str, dict] = Field(default={})  # {"a": {"x": 100, "y": 200}, ...}

class KeyboardMappingUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=80)
    layout_type: Optional[str] = Field(None, pattern=r"^(qwerty|number)$")
    keys_json: Optional[dict[str, dict]] = None
