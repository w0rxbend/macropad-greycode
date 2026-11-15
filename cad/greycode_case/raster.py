"""A small z-buffer rasteriser in numpy, so the pictures need no GPU and no window system.

Flat-shaded triangles, two lights, inked edges where depth jumps or faces meet at an angle,
2 x 2 supersampling.
"""

from dataclasses import dataclass

import numpy as np
from build123d import Part

SUPERSAMPLE = 2
MESH_TOLERANCE = 0.03
KEY_LIGHT = np.array([-0.45, -0.6, 0.66])
FILL_LIGHT = np.array([0.7, 0.3, 0.25])
AMBIENT = 0.32
BACKGROUND = np.array([0.94, 0.94, 0.95])
INK = 0.25
CREASE_COSINE = 0.85
DEPTH_JUMP = 0.01  # share of the depth; a bigger jump between neighbouring pixels is an outline
ORTHO_DEPTH_JUMP = 0.3  # mm, the same for straight views
HEADLIGHT = 0.3  # light from the camera, so a view from below is not black


@dataclass(frozen=True)
class Look:
    colour: tuple[float, float, float]
    glow: bool = False  # lit from inside: drawn at full colour, no shading


@dataclass
class Mesh:
    triangles: np.ndarray  # (n, 3, 3)
    colours: np.ndarray  # (n, 3)
    glow: np.ndarray  # (n,) bool


@dataclass(frozen=True)
class Camera:
    eye: tuple[float, float, float]
    target: tuple[float, float, float]
    up: tuple[float, float, float] = (0.0, 0.0, 1.0)
    field_of_view: float = 25.0  # degrees, vertical; ignored when `ortho_height` is set
    ortho_height: float | None = None  # mm shown top to bottom, for straight views


def mesh_of(part: Part, look: Look, section: tuple[int, float, tuple[float, float, float]] | None = None) -> Mesh:
    """Triangles of a part. With `section` = (axis, position, colour), faces lying on that cut plane
    get the section colour."""
    vertices, faces = part.tessellate(MESH_TOLERANCE, 0.15)
    points = np.array([tuple(vertex) for vertex in vertices], dtype=float)
    triangles = points[np.array(faces, dtype=int)]
    colours = np.tile(np.array(look.colour, dtype=float), (len(triangles), 1))
    if section is not None:
        axis, position, colour = section
        on_plane = np.all(np.abs(triangles[:, :, axis] - position) < 1e-4, axis=1)
        colours[on_plane] = colour
    return Mesh(triangles, colours, np.full(len(triangles), look.glow))


def render(meshes: list[Mesh], camera: Camera, size: tuple[int, int]) -> np.ndarray:
    width, height = size[0] * SUPERSAMPLE, size[1] * SUPERSAMPLE
    triangles = np.concatenate([mesh.triangles for mesh in meshes])
    colours = np.concatenate([mesh.colours for mesh in meshes])
    glow = np.concatenate([mesh.glow for mesh in meshes])
    right, up, forward = _axes(camera)
    relative = triangles - np.array(camera.eye)
    view = np.stack([relative @ right, relative @ up, relative @ forward], axis=-1)
    screen = _project(view, camera, width, height)
    normals = _facing_normals(triangles, relative)
    shaded = _shade(colours, normals, glow, forward)
    depth, owner = _rasterise(screen, view[:, :, 2], width, height)
    picture = np.where(owner[..., None] >= 0, shaded[np.maximum(owner, 0)], BACKGROUND)
    picture *= 1 - (1 - INK) * _edges(depth, owner, normals, camera.ortho_height is not None)[..., None]
    picture = picture.reshape(size[1], SUPERSAMPLE, size[0], SUPERSAMPLE, 3).mean(axis=(1, 3))
    return np.clip(picture, 0, 1)


def _axes(camera: Camera) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    forward = _unit(np.subtract(camera.target, camera.eye))
    right = _unit(np.cross(forward, camera.up))
    return right, np.cross(right, forward), forward


def _project(view: np.ndarray, camera: Camera, width: int, height: int) -> np.ndarray:
    if camera.ortho_height is not None:
        scale = np.full(view.shape[:2], height / camera.ortho_height)
    else:
        scale = (height / 2) / np.tan(np.radians(camera.field_of_view) / 2) / np.maximum(view[:, :, 2], 1e-6)
    return np.stack([width / 2 + view[:, :, 0] * scale, height / 2 - view[:, :, 1] * scale], axis=-1)


def _facing_normals(triangles: np.ndarray, relative: np.ndarray) -> np.ndarray:
    """Unit normals turned toward the camera, so the winding of the mesh does not matter."""
    normals = np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])
    normals /= np.maximum(np.linalg.norm(normals, axis=1, keepdims=True), 1e-12)
    away = (normals * relative.mean(axis=1)).sum(axis=1) > 0
    normals[away] *= -1
    return normals


def _shade(colours: np.ndarray, normals: np.ndarray, glow: np.ndarray, forward: np.ndarray) -> np.ndarray:
    key = np.clip(normals @ _unit(KEY_LIGHT), 0, None)
    fill = np.clip(normals @ _unit(FILL_LIGHT), 0, None)
    light = AMBIENT + 0.62 * key + 0.22 * fill + HEADLIGHT * np.clip(-(normals @ forward), 0, None)
    shaded = colours * light[:, None] + 0.12 * key[:, None] ** 8
    return np.where(glow[:, None], colours, shaded)


def _rasterise(screen: np.ndarray, depth_of: np.ndarray, width: int, height: int) -> tuple[np.ndarray, np.ndarray]:
    depth = np.full((height, width), np.inf)
    owner = np.full((height, width), -1, dtype=np.int64)
    for index in range(len(screen)):
        (x0, y0), (x1, y1), (x2, y2) = screen[index]
        left, right = max(int(np.floor(min(x0, x1, x2))), 0), min(int(np.ceil(max(x0, x1, x2))), width - 1)
        top, bottom = max(int(np.floor(min(y0, y1, y2))), 0), min(int(np.ceil(max(y0, y1, y2))), height - 1)
        area = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
        if left > right or top > bottom or abs(area) < 1e-9:
            continue
        xs, ys = np.meshgrid(np.arange(left, right + 1) + 0.5, np.arange(top, bottom + 1) + 0.5)
        w0 = ((x1 - xs) * (y2 - ys) - (x2 - xs) * (y1 - ys)) / area
        w1 = ((x2 - xs) * (y0 - ys) - (x0 - xs) * (y2 - ys)) / area
        w2 = 1 - w0 - w1
        inside = (w0 >= -1e-6) & (w1 >= -1e-6) & (w2 >= -1e-6)
        z = w0 * depth_of[index, 0] + w1 * depth_of[index, 1] + w2 * depth_of[index, 2]
        window = depth[top : bottom + 1, left : right + 1]
        nearer = inside & (z < window)
        window[nearer] = z[nearer]
        owner[top : bottom + 1, left : right + 1][nearer] = index
    return depth, owner


def _edges(depth: np.ndarray, owner: np.ndarray, normals: np.ndarray, straight: bool) -> np.ndarray:
    filled = owner >= 0
    normal = normals[np.maximum(owner, 0)]
    finite = np.where(filled, depth, depth[filled].max() * 2 if filled.any() else 1.0)
    edges = np.zeros(depth.shape, dtype=bool)
    for axis in (0, 1):
        nearer = np.minimum(np.delete(finite, -1, axis=axis), np.delete(finite, 0, axis=axis))
        jump = np.abs(np.diff(finite, axis=axis)) > (ORTHO_DEPTH_JUMP if straight else DEPTH_JUMP * nearer)
        crease = (np.delete(normal, -1, axis=axis) * np.delete(normal, 0, axis=axis)).sum(axis=-1) < CREASE_COSINE
        border = np.delete(filled, -1, axis=axis) != np.delete(filled, 0, axis=axis)
        line = jump | crease | border
        pad = [(0, 0), (0, 0)]
        pad[axis] = (0, 1)
        edges |= np.pad(line, pad)
    return edges.astype(float)


def _unit(vector) -> np.ndarray:
    vector = np.asarray(vector, dtype=float)
    return vector / np.linalg.norm(vector)
