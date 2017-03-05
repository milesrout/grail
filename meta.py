# Meta-programming stuff. None of this is strictly necessary, but can be
# helpful.

from abc import ABCMeta, abstractmethod

class HttpConnection(metaclass=ABCMeta):
    pass
