from typing import List, Optional
from fastmcp import FastMCP

mcp = FastMCP(
    name="Sudoku",
    json_response=True
)

class Sudoku:
    size: int 
    board: List[List[int]]
    root: int


    def __init__(self, size: int = 3, board: Optional[List[List[int]]] = None):
        if board is None:
            self.size = size
            self.board = [[0 for _ in range(size)] for _ in range(size)]
        else:
            self.size = len(board)
            if len(board) != size or any(len(row) != size for row in board):
                raise ValueError("board must be sizexsize")
            self.board = [row[:] for row in board]        
        self.root = int(self.size ** 0.5)

    def _get_row(self, r: int) -> List[int]:
        row = self.board[r][:]
        return row 

    def _get_column(self, c: int) -> List[int]:
        column = [self.board[r][c] for r in range(self.size)]
        return column

    def _get_square(self, r: int, c: int) -> List[List[int]]:
        br = (r // self.root) * self.root
        bc = (c // self.root) * self.root
        square = [
            [self.board[i][j] for j in range(bc, bc + self.root)]
            for i in range(br, br + self.root)
        ]
        return square
    
    def _get_puzzle(self):
        return self.board

    def _fill_cell(self, row, col, number):
        self.board[row][col] = number
        return self._get_puzzle()


        
if __name__ == "__main__":
    puzzle_3x3 = [
        [2,4,9,3,6,0,7,1,0],
        [0,5,6,0,7,1,0,0,0],
        [7,0,0,0,4,0,6,3,0],
        [0,0,0,7,8,0,0,9,0],
        [8,7,0,6,2,9,0,5,3],
        [0,9,0,0,5,4,0,0,0],
        [0,6,7,0,1,0,0,0,2],
        [0,0,0,8,3,0,9,6,0],
        [0,3,8,0,9,6,5,4,7],
    ]
    puzzle_2x2 = [
        [1,2,3,0],
        [0,4,0,2],
        [2,0,4,0],
        [0,3,0,1],
    ]


    sudoku = Sudoku(size=4, board=puzzle_2x2)


    @mcp.tool()
    def get_row(r: int) -> List[int]:
        """
        Return the r-th row of the Sudoku board.

        Parameters
        ----------
        r : int
            Zero-based row index (0..size-1).

        Returns
        -------
        List[int]
            A list of length `size` with the values in row `r`. `0` denotes an empty cell.

        Notes
        -----
        Read-only; does not modify the board.
        """
        return sudoku._get_row(r=r)


    @mcp.tool()
    def get_column(c: int) -> List[int]:
        """
        Return the c-th column of the Sudoku board.

        Parameters
        ----------
        c : int
            Zero-based column index (0..size-1).

        Returns
        -------
        List[int]
            A list of length `size` with the values in column `c`. `0` denotes an empty cell.

        Notes
        -----
        Read-only; does not modify the board.
        """
        return sudoku._get_column(c=c)


    @mcp.tool()
    def get_square(r: int, c: int) -> List[List[int]]:
        """
        Return the sub-square (box) that contains cell (r, c) as a 2D nested list.

        Parameters
        ----------
        r : int
            Zero-based row index of any cell inside the desired box.
        c : int
            Zero-based column index of any cell inside the desired box.

        Returns
        -------
        List[List[int]]
            The values in the box as a 2D nested list of shape (root × root)
            (e.g., 3x3 nested list for a 9x9 puzzle where `root=3`). `0` denotes an empty cell.

        Notes
        -----
        For a 9x9 puzzle the board is partitioned into 3x3 boxes.
        The nested list preserves the 2D structure of the box.
        Read-only; does not modify the board.
        """
        return sudoku._get_square(r=r, c=c)


    @mcp.tool()
    def get_puzzle() -> List[List[int]]:
        """
        Return the entire Sudoku board.

        Returns
        -------
        List[List[int]]
            A 2D list of shape (size × size). `0` denotes an empty cell.

        Notes
        -----
        Read-only; does not modify the board. Useful for agents to inspect full state.
        """
        return sudoku._get_puzzle()


    @mcp.tool()
    def fill_cell(row: int, col: int, number: int) -> List[List[int]]:
        """
        Set a single cell and return the updated board.

        Parameters
        ----------
        row : int
            Zero-based row index (0 to size-1)
        col : int
            Zero-based column index (0 to size-1)
        number : int
            Value to place (1 to size). Use `0` to clear the cell.

        Returns
        -------
        List[List[int]]
            The entire board after the update.

        Notes
        -----
        This function validates basic constraints but does not check full Sudoku legality.
        It ensures the cell is empty (contains 0) and the number is in valid range.
        """
        # Validate row and column bounds
        if not (0 <= row < sudoku.size):
            raise ValueError(f"Row index {row} out of bounds. Must be 0 to {sudoku.size-1}")
        if not (0 <= col < sudoku.size):
            raise ValueError(f"Column index {col} out of bounds. Must be 0 to {sudoku.size-1}")
        
        # Validate number range
        if not (0 <= number <= sudoku.size):
            raise ValueError(f"Number {number} out of range. Must be 0 to {sudoku.size}")
        
        # Check if cell is empty (only allow filling empty cells unless clearing with 0)
        if sudoku.board[row][col] != 0 and number != 0:
            raise ValueError(f"Cell at ({row}, {col}) already contains {sudoku.board[row][col]}. Only empty cells (0) can be filled.")
        
        # Fill the cell and return the updated board
        sudoku._fill_cell(row=row, col=col, number=number)
        return sudoku._get_puzzle()


    # @mcp.tool()
    def get_empty_cells() -> List[List[int]]:
        """
        Return a list of all empty cells (cells containing 0) in the Sudoku board.

        Returns
        -------
        List[List[int]]
            A list of [row, col] pairs representing empty cells.
            Each pair uses zero-based indexing.

        Notes
        -----
        Useful for agents to identify which cells can be filled.
        Returns empty list if no empty cells exist (puzzle is complete).
        """
        empty_cells = []
        for r in range(sudoku.size):
            for c in range(sudoku.size):
                if sudoku.board[r][c] == 0:
                    empty_cells.append([r, c])
        return empty_cells

    # @mcp.tool()
    def get_possible_numbers(row: int, col: int) -> List[int]:
        """
        Get possible numbers that can be placed in a specific cell without violating Sudoku rules.

        Parameters
        ----------
        row : int
            Zero-based row index
        col : int
            Zero-based column index

        Returns
        -------
        List[int]
            List of numbers (1 to size) that can be legally placed in the cell.
            Returns empty list if cell is already filled or no valid numbers exist.

        Notes
        -----
        Checks row, column, and box constraints to determine valid numbers.
        """
        if sudoku.board[row][col] != 0:
            return []  # Cell is already filled
        
        # Get used numbers in row, column, and box
        used_in_row = set(sudoku._get_row(row))
        used_in_col = set(sudoku._get_column(col))
        square_2d = sudoku._get_square(row, col)
        used_in_box = set(cell for row_in_box in square_2d for cell in row_in_box)
        
        # Find all used numbers
        used_numbers = used_in_row | used_in_col | used_in_box
        used_numbers.discard(0)  # Remove 0 (empty cells)
        
        # Return numbers not used
        all_numbers = set(range(1, sudoku.size + 1))
        possible = list(all_numbers - used_numbers)
        return sorted(possible)


    mcp.run(transport="streamable-http", host="0.0.0.0", port=8081)