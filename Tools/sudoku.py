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

    def _get_square(self, r: int, c: int) -> List[int]:
        br = (r // self.root) * self.root
        bc = (c // self.root) * self.root
        square = [
            self.board[i][j]
            for i in range(br, br + self.root)
            for j in range(bc, bc + self.root)
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
    def get_square(r: int, c: int) -> List[int]:
        """
        Return the sub-square (box) that contains cell (r, c), flattened row-wise.

        Parameters
        ----------
        r : int
            Zero-based row index of any cell inside the desired box.
        c : int
            Zero-based column index of any cell inside the desired box.

        Returns
        -------
        List[int]
            The values in the box as a flat list of length `root*root`
            (e.g., 9 values for a 9x9 puzzle where `root=3`). `0` denotes an empty cell.

        Notes
        -----
        For a 9x9 puzzle the board is partitioned into 3x3 boxes.
        The list is ordered from the top-left of the box to the bottom-right.
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
            row index starting with 1 to the size of the board
        col : int
            column index starting with 1 to the size of the board
        number : int
            Value to place. Use `0` to clear the cell.

        Returns
        -------
        List[List[int]]
            The entire board after the update.

        Notes
        -----
        This function does not validate Sudoku legality (row/column/box rules).
        Callers should ensure `number` is a legal candidate for (row, col) before writing.
        """
        if sudoku.board[row][col] != 0:
            return "You can only fill cells that contain a 0."
        if sudoku.size < sudoku.board[row][col] < 1:
            return f"You can only fill in numbers that are between {sudoku.size+1} and 0."
        sudoku._fill_cell(row=row, col=col, number=number)
        return sudoku._get_puzzle()


    mcp.run(transport="streamable-http", host="0.0.0.0", port=8081)