"""Default room program and required relationships for the prototype."""

from testfit.optimizer import Room, RoomRelationship


DEFAULT_ROOMS = (
    Room("Living Room", 5.0, 4.0),
    Room("Bedroom 1", 4.0, 4.0),
    Room("Bathroom 1", 2.0, 2.0),
    Room("Bedroom 2", 4.0, 4.0),
    Room("Bathroom 2", 2.0, 2.0),
    Room("Kitchen", 4.0, 3.0),
    Room("Dining", 3.0, 3.0),
)

DEFAULT_RELATIONSHIPS = (
    RoomRelationship("Bedroom 1", "Bathroom 1", "ATTACHED"),
    RoomRelationship("Bedroom 2", "Bathroom 2", "ATTACHED"),
    RoomRelationship("Kitchen", "Dining", "ADJACENT"),
    RoomRelationship("Living Room", "Dining", "NEAR"),
    RoomRelationship("Kitchen", "Dining", "PREFERRED"),
)