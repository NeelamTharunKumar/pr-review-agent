import pytest
from app.rag.chunkers import (
    chunk_javascript,
    chunk_go,
    chunk_rust,
    chunk_file,
    _chunk_by_lines,
    LANGUAGE_CHUNKERS,
)


class TestChunkJavaScript:
    def test_single_function(self):
        content = "function hello() {\n  return 1;\n}\n"
        chunks = chunk_javascript("test.js", content)
        assert len(chunks) >= 1
        assert chunks[0]["type"] == "function/class"
        assert "hello" in chunks[0]["name"]

    def test_multiple_functions(self):
        content = "function a() { return 1; }\n\nfunction b() { return 2; }\n"
        chunks = chunk_javascript("test.js", content)
        assert len(chunks) >= 1

    def test_class_detection(self):
        content = "class Foo {\n  constructor() {}\n  bar() {}\n}\n"
        chunks = chunk_javascript("test.js", content)
        assert len(chunks) >= 1
        assert chunks[0]["name"] == "Foo"

    def test_arrow_function(self):
        content = "const add = (a, b) => a + b;\n"
        chunks = chunk_javascript("test.js", content)
        assert len(chunks) >= 1

    def test_empty_content(self):
        chunks = chunk_javascript("test.js", "")
        assert chunks == []

    def test_short_content_fallback(self):
        content = "console.log('hi');"
        chunks = chunk_javascript("test.js", content)
        assert len(chunks) == 1
        assert chunks[0]["type"] == "module"

    def test_small_chunks_filtered(self):
        content = "\n\n\n" * 50
        chunks = chunk_javascript("test.js", content)
        assert len(chunks) == 0

    def test_typescript_file(self):
        content = "function greet(name: string): string {\n  return `Hello ${name}`;\n}\n"
        chunks = chunk_javascript("test.ts", content)
        assert len(chunks) >= 1

    def test_jsx_file(self):
        content = "export default function App() {\n  return <div>Hello</div>;\n}\n"
        chunks = chunk_javascript("App.jsx", content)
        assert len(chunks) >= 1


class TestChunkGo:
    def test_single_function(self):
        content = "func hello() {\n\tfmt.Println(\"hi\")\n}\n"
        chunks = chunk_go("test.go", content)
        assert len(chunks) >= 1
        assert "hello" in chunks[0]["name"]
        assert chunks[0]["type"] == "function"

    def test_method(self):
        content = "func (s *Server) Start() error {\n\treturn nil\n}\n"
        chunks = chunk_go("test.go", content)
        assert len(chunks) >= 1

    def test_struct(self):
        content = "type User struct {\n\tName string\n\tAge  int\n}\n"
        chunks = chunk_go("test.go", content)
        assert len(chunks) >= 1
        assert chunks[0]["type"] == "struct"

    def test_interface(self):
        content = "type Reader interface {\n\tRead(p []byte) (n int, err error)\n}\n"
        chunks = chunk_go("test.go", content)
        assert len(chunks) >= 1
        assert chunks[0]["type"] == "interface"

    def test_empty_content(self):
        chunks = chunk_go("test.go", "")
        assert chunks == []

    def test_short_content_fallback(self):
        content = "package main\n"
        chunks = chunk_go("test.go", content)
        assert len(chunks) == 1
        assert chunks[0]["type"] == "package"


class TestChunkRust:
    def test_function(self):
        content = "fn add(a: i32, b: i32) -> i32 {\n    a + b\n}\n"
        chunks = chunk_rust("test.rs", content)
        assert len(chunks) >= 1
        assert chunks[0]["name"] == "add"
        assert chunks[0]["type"] == "function"

    def test_pub_fn(self):
        content = "pub fn hello() {\n    println!(\"hi\");\n}\n"
        chunks = chunk_rust("test.rs", content)
        assert len(chunks) >= 1

    def test_struct(self):
        content = "pub struct Point {\n    x: f64,\n    y: f64,\n}\n"
        chunks = chunk_rust("test.rs", content)
        assert len(chunks) >= 1
        assert chunks[0]["type"] == "struct"

    def test_impl(self):
        content = "impl Point {\n    fn new() -> Self { Point { x: 0.0, y: 0.0 } }\n}\n"
        chunks = chunk_rust("test.rs", content)
        assert len(chunks) >= 1
        assert chunks[0]["type"] == "impl"

    def test_enum(self):
        content = "pub enum Color {\n    Red,\n    Green,\n    Blue,\n}\n"
        chunks = chunk_rust("test.rs", content)
        assert len(chunks) >= 1
        assert chunks[0]["type"] == "enum"

    def test_trait(self):
        content = "trait Drawable {\n    fn draw(&self);\n}\n"
        chunks = chunk_rust("test.rs", content)
        assert len(chunks) >= 1
        assert chunks[0]["type"] == "trait"

    def test_empty_content(self):
        chunks = chunk_rust("test.rs", "")
        assert chunks == []

    def test_short_content_fallback(self):
        content = "use std::io;\n"
        chunks = chunk_rust("test.rs", content)
        assert len(chunks) == 1
        assert chunks[0]["type"] == "module"


class TestChunkFileDispatch:
    def test_python_calls_python_chunker(self):
        called = []

        def fake_py_chunker(fp, c):
            called.append(fp)
            return [{"text": c, "filepath": fp, "start_line": 1, "end_line": 1, "type": "function", "name": "x"}]

        result = chunk_file("app.py", "def foo(): pass", fake_py_chunker)
        assert called == ["app.py"]
        assert len(result) == 1

    def test_javascript_dispatch(self):
        result = chunk_file("app.js", "function foo() { return 1; }", lambda fp, c: [])
        assert len(result) >= 1

    def test_go_dispatch(self):
        result = chunk_file("app.go", "func hello() {}", lambda fp, c: [])
        assert len(result) >= 1

    def test_rust_dispatch(self):
        result = chunk_file("app.rs", "fn hello() {}", lambda fp, c: [])
        assert len(result) >= 1

    def test_unknown_extension_fallback(self):
        result = chunk_file("app.xyz", "hello world\n" * 100, lambda fp, c: [])
        assert len(result) >= 1

    def test_language_chunkers_coverage(self):
        assert ".js" in LANGUAGE_CHUNKERS
        assert ".ts" in LANGUAGE_CHUNKERS
        assert ".go" in LANGUAGE_CHUNKERS
        assert ".rs" in LANGUAGE_CHUNKERS
        assert ".vue" in LANGUAGE_CHUNKERS
        assert ".jsx" in LANGUAGE_CHUNKERS
        assert ".tsx" in LANGUAGE_CHUNKERS


class TestChunkByLines:
    def test_basic(self):
        content = "\n".join([f"line {i}" for i in range(100)])
        chunks = _chunk_by_lines("test.txt", content)
        assert len(chunks) >= 1
        assert chunks[0]["type"] == "chunk"

    def test_empty(self):
        chunks = _chunk_by_lines("test.txt", "")
        assert len(chunks) == 0

    def test_short(self):
        chunks = _chunk_by_lines("test.txt", "hello\nworld")
        assert len(chunks) == 1

    def test_line_numbers(self):
        content = "\n".join([f"line {i}" for i in range(150)])
        chunks = _chunk_by_lines("test.txt", content)
        assert chunks[0]["start_line"] == 1
        assert chunks[0]["end_line"] <= 150
