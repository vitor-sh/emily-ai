import os
import llm
from modelo import conversar_com_ferramentas

def test():
    conversar_com_ferramentas('fecha o vscode', callback=print)
    
if __name__ == "__main__":
    test()
