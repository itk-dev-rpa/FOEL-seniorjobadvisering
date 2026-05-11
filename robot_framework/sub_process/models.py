"""This module contains common dataclasses used in the process."""

from dataclasses import dataclass, field

from itk_dev_shared_components.misc import cpr_util


@dataclass
class Employee:
    """A dataclass representing a employee."""
    cpr: str
    name: str
    number: str
    occupation: str
    birthday: str
    email: str | None = None

    def to_mail_string(self):
        """Convert the employee to a simple string
        to be used in the supervisor email."""
        return f"{self.name} ({self.number}) - {self.occupation} - {self.birthday}"

    def to_dict(self):
        """Convert the employee object to a dict
        to be used in a queue element."""
        return {
            "cpr": self.cpr,
            "name": self.name,
            "email": self.email
        }


@dataclass
class Supervisor:
    """A dataclass representing a supervisor"""
    name: str
    email: str
    employees: list[Employee] = field(default_factory=list, init=False)

    def to_dict(self):
        """Convert the Supervisor object to a dict
        to be used in a queue element."""
        return {
            "name": self.name,
            "email": self.email,
            "employees": [
                w.to_mail_string() for w in self.employees
            ]
        }

    def to_dict_mba(self):
        """Convert the Supervisor object to a dict
        to be used in a queue element. Specific to
        the MBA flow.
        """
        return {
            "name": self.name,
            "email": self.email,
            "employees": [
                {
                    "name": w.name,
                    "age": cpr_util.get_age(w.cpr)
                }
                for w in self.employees
            ]
        }
