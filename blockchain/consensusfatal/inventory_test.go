package consensusfatal

import (
	"go/ast"
	"go/parser"
	"go/token"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
)

// TestNoConsensusFatalPanicLeft asserts H-1 remediation: CONSENSUS_FATAL
// conditions must terminate via HaltErr/Haltf/os.Exit (or the IAVL local
// halt), never panic(fmt.Errorf("CONSENSUS_FATAL...")). CometBFT recovers
// panics on the consensus goroutine and leaves a zombie process.
func TestNoConsensusFatalPanicLeft(t *testing.T) {
	root := findBlockchainRoot(t)

	var offenders []string
	err := filepath.Walk(root, func(path string, info os.FileInfo, err error) error {
		if err != nil {
			return err
		}
		if info.IsDir() {
			base := info.Name()
			if base == "vendor" || base == ".git" {
				return filepath.SkipDir
			}
			return nil
		}
		if !strings.HasSuffix(path, ".go") {
			return nil
		}
		// Patch test files may mention the old panic form in comments/docs.
		if strings.HasSuffix(path, "_test.go") && strings.Contains(path, string(filepath.Separator)+"patches"+string(filepath.Separator)) {
			return nil
		}
		data, readErr := os.ReadFile(path)
		if readErr != nil {
			return readErr
		}
		fset := token.NewFileSet()
		file, parseErr := parser.ParseFile(fset, path, data, 0)
		if parseErr != nil {
			return parseErr
		}
		ast.Inspect(file, func(node ast.Node) bool {
			call, ok := node.(*ast.CallExpr)
			if !ok {
				return true
			}
			fn, ok := call.Fun.(*ast.Ident)
			if !ok || fn.Name != "panic" {
				return true
			}
			tagged := false
			for _, arg := range call.Args {
				ast.Inspect(arg, func(inner ast.Node) bool {
					lit, ok := inner.(*ast.BasicLit)
					if ok && strings.Contains(lit.Value, "CONSENSUS_FATAL") {
						tagged = true
					}
					return !tagged
				})
			}
			if tagged {
				rel, _ := filepath.Rel(root, path)
				pos := fset.Position(call.Pos())
				offenders = append(offenders, rel+":"+strconv.Itoa(pos.Line))
			}
			return true
		})
		return nil
	})
	if err != nil {
		t.Fatalf("walk blockchain: %v", err)
	}
	if len(offenders) > 0 {
		t.Fatalf("CONSENSUS_FATAL must use consensusfatal.HaltErr/Haltf (or IAVL consensusFatalHalt), not panic:\n  %s",
			strings.Join(offenders, "\n  "))
	}
}

func findBlockchainRoot(t *testing.T) string {
	t.Helper()
	wd, err := os.Getwd()
	if err != nil {
		t.Fatalf("getwd: %v", err)
	}
	// Running as ./consensusfatal/... → parent is blockchain/
	dir := wd
	for {
		if filepath.Base(dir) == "blockchain" {
			return dir
		}
		parent := filepath.Dir(dir)
		if parent == dir {
			t.Fatalf("could not find blockchain/ root from %s", wd)
		}
		dir = parent
	}
}
