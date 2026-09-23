from abc import ABC, abstractmethod
from app.db.models import CalendarEvent
from app.services.application import serialize


class CalendarService(ABC):
    @abstractmethod
    def get_events(self): ...

    @abstractmethod
    def create_event(self, data): ...

    @abstractmethod
    def update_event(self, ident, data): ...

    @abstractmethod
    def delete_event(self, ident): ...

    @abstractmethod
    def find_free_slots(self, request): ...


class InternalCalendarService(CalendarService):
    def __init__(self, application):
        self.application = application

    def get_events(self):
        return [serialize(e) for e in self.application.rows(CalendarEvent)]

    def create_event(self, data):
        return self.application.save_event(data)

    def update_event(self, ident, data):
        return self.application.save_event(data, ident)

    def delete_event(self, ident):
        return self.application.delete_event(ident)

    def find_free_slots(self, request):
        return self.application.plan(request, persist=False)
