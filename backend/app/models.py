from typing import Literal
from pydantic import BaseModel, EmailStr, Field, ConfigDict

Role = Literal["Founder", "Core Management", "Member"]
MemberStatus = Literal["Pending", "Active", "Suspended"]
TaskStatus = Literal["Todo", "In progress", "Review", "Done"]
Priority = Literal["Low", "Medium", "High"]

class RegisterIn(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)
    team: str = Field(default="Unassigned", max_length=80)

class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)

class MemberCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    email: EmailStr
    role: Role = "Member"
    team: str = Field(default="Unassigned", max_length=80)
    status: MemberStatus = "Pending"
    password: str = Field(min_length=12, max_length=128)

class MemberPatch(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=100)
    role: Role | None = None
    team: str | None = Field(default=None, max_length=80)
    status: MemberStatus | None = None

class TaskCreate(BaseModel):
    title: str = Field(min_length=3, max_length=180)
    description: str = Field(default="", max_length=4000)
    assignee_id: str
    priority: Priority = "Medium"
    due_date: str | None = None
    project: str = Field(default="Club projects", max_length=100)

class TaskPatch(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=180)
    description: str | None = Field(default=None, max_length=4000)
    assignee_id: str | None = None
    priority: Priority | None = None
    status: TaskStatus | None = None
    due_date: str | None = None
    submission_note: str | None = Field(default=None, max_length=2000)

class TeamCreate(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    description: str = Field(default="", max_length=500)

class UserPublic(BaseModel):
    id: str
    member_id: str
    name: str
    email: EmailStr
    role: Role
    team: str
    status: MemberStatus
    model_config = ConfigDict(extra="ignore")
