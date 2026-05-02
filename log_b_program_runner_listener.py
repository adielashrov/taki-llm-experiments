from bppy.execution.listeners.b_program_runner_listener import BProgramRunnerListener


class LogBProgramRunnerListener(BProgramRunnerListener):
    """
    This class implements the :class:`BProgramRunnerListener
    <bppy.execution.listeners.b_program_runner_listener.BProgramRunnerListener>` interface, providing basic print
    statements for specific events in the BProgram's execution.
    """
    def starting(self, b_program):
        """
        Logs "STARTED" when the BProgram execution is about to start.
        """
        if self.__logger:
            self.__logger.info("STARTED")
        else:
            print("STARTED")

    def started(self, b_program):
        pass

    def super_step_done(self, b_program):
        pass

    def ended(self, b_program):
        """
        Logs "ENDED" when the BProgram execution is about to start.
        """
        if self.__logger:
            self.__logger.info("ENDED")
        else:
            print("ENDED")


    def assertion_failed(self, b_program):
        pass

    def b_thread_added(self, b_program):
        pass

    def b_thread_removed(self, b_program):
        pass

    def b_thread_done(self, b_program):
        pass

    def event_selected(self, b_program, event):
        """
        Logs the selected event when an event has been selected during the BProgram's execution.
        """
        if self.__logger:
            self.__logger.info(event)
        else:
            print(event)

    def halted(self, b_program):
        pass

    def __init__(self, logger=None):
        """
        Initializes the PrintBProgramRunnerListener.
        """
        super().__init__()
        self.__logger = logger