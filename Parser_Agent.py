class CodeParserAgent:

    def parse(self, code):

        print("\nAgent 1 (Code Parser Agent) started...")

        # Split code into lines
        lines = code.split("\n")

        variables = []
        functions = []
        control_flow = []

        for line_number, line in enumerate(lines, start=1):

            line = line.strip()

            # Detect variables
            if line.startswith(("int ", "float ", "double ", "char ")):
                variables.append((line_number, line))

            # Detect function calls
            if "(" in line and ")" in line:
                functions.append((line_number, line))

            # Detect control flow
            if any(keyword in line for keyword in ["if", "for", "while", "switch"]):
                control_flow.append((line_number, line))

        parsed_data = {
            "lines": lines,
            "variables": variables,
            "functions": functions,
            "control_flow": control_flow
        }

        print("Agent 1 finished parsing the code")

        return parsed_data
