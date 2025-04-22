try:
    import readline
except ImportError:
    import pyreadline3 as readline
from typing import Callable, Dict

class CommandInterface:
    def __init__(self):
        self.commands: Dict[str, Callable] = {}
        self._setup_command_completion()
        
    def register_command(self, command: str, handler: Callable, help_text: str = ""):
        """註冊一個指令及其處理器"""
        self.commands[command] = {"handler": handler, "help": help_text}
        
    def _setup_command_completion(self):
        def completer(text, state):
            options = [cmd for cmd in self.commands.keys() if cmd.startswith(text)]
            return options[state] if state < len(options) else None

        readline.parse_and_bind("tab: complete")
        readline.set_completer(completer)
        
    def process_command(self, cmd_line: str) -> bool:
        """處理使用者輸入的指令，返回是否應繼續執行"""
        cmd_parts = cmd_line.strip().split()
        if not cmd_parts:
            return True
            
        cmd = cmd_parts[0].lower()
        
        # 精確匹配指令
        if cmd in self.commands:
            return self.commands[cmd]["handler"](cmd_line)
            
        # 前綴匹配指令（如 "set interval"）
        for registered_cmd in self.commands:
            if cmd_line.lower().startswith(registered_cmd):
                return self.commands[registered_cmd]["handler"](cmd_line)
                
        print("未知指令，輸入 help 查看可用指令。")
        return True
        
    def show_help(self) -> bool:
        """顯示所有已註冊指令的幫助信息"""
        print("可用指令：")
        for cmd, info in self.commands.items():
            print(f" - {cmd}: {info['help']}")
        return True
        
    def start_interactive_loop(self, prompt: str = ">> "):
        """開始交互命令循環"""
        print("輸入指令（輸入 help 查看指令列表）")
        
        try:
            while True:
                try:
                    cmd = input(prompt).strip()
                    if not self.process_command(cmd):
                        break
                except (EOFError, KeyboardInterrupt):
                    print("\n收到退出信號")
                    break
        except Exception as e:
            print(f"指令處理時發生錯誤: {e}")
