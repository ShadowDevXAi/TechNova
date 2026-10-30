from typing import Literal
from pydantic import BaseModel, EmailStr, Field, ConfigDict

Role = Literal["Founder", "Core Management", "Faculty", "Member"]
MemberStatus = Literal["Pending", "Active", "Suspended"]
TaskStatus = Literal["Todo", "In progress", "Review", "Done"]
Priority = Literal["Low", "Medium", "High"]
TaskDifficulty = Literal["F", "E", "D", "C", "B", "A", "S", "SS", "SSS"]
ProgrammingLanguage = Literal["General", "C", "C++", "C#", "Java", "Python", "JavaScript", "TypeScript", "HTML/CSS", "React", "FastAPI", "SQL / MongoDB", "Godot / GDScript", "Other"]

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
    assignee_id: str | None = None
    assignee_ids: list[str] = Field(default_factory=list, max_length=100)
    assignment_mode: Literal["individual", "selected_members", "open_to_all"] = "individual"
    priority: Priority = "Medium"
    difficulty_rank: TaskDifficulty = "F"
    programming_language: ProgrammingLanguage = "General"
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
    submission_evidence_url: str | None = Field(default=None, max_length=1200)
    project_url: str | None = Field(default=None, max_length=1200)
    submission_attested: bool | None = None
    review_feedback: str | None = Field(default=None, max_length=2000)

class TaskBulkConfirm(BaseModel):
    task_ids: list[str] = Field(min_length=1, max_length=100)


class AnnouncementCreate(BaseModel):
    title: str = Field(min_length=3, max_length=120)
    message: str = Field(min_length=3, max_length=3000)


class TaskCompletionConfirm(BaseModel):
    card_token: str = Field(min_length=30, max_length=200)


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
