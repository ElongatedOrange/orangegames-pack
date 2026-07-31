#version 330

// HUD element repositioning for 1.21.11 (formats 75-83, uniform-block era).
// Vanilla rendertype_text.vsh plus the position decode; fsh stays vanilla.
#define HEIGHT_BIT 13
#define MAX_BIT 10
#define ADD_OFFSET 4095
#define DEFAULT_OFFSET 10

#moj_import <minecraft:fog.glsl>
#moj_import <minecraft:dynamictransforms.glsl>
#moj_import <minecraft:projection.glsl>

in vec3 Position;
in vec4 Color;
in vec2 UV0;
in ivec2 UV2;

uniform sampler2D Sampler2;

out float sphericalVertexDistance;
out float cylindricalVertexDistance;
out vec4 vertexColor;
out vec2 texCoord0;

void main() {
    vec3 pos = Position;
    vertexColor = Color * texelFetch(Sampler2, UV2 / 16, 0);

    // element id is encoded in the high bits of glyph Y; GUI ortho pass only
    vec2 ui = ceil(2.0 / vec2(ProjMat[0][0], -ProjMat[1][1]));
    if (pos.y >= ui.y && ProjMat[3].x == -1.0) {
        int bit = int(pos.y) >> HEIGHT_BIT;
        if (((bit >> MAX_BIT) & 1) == 1) {
            int id = bit - (1 << MAX_BIT);
            pos.x -= 0.5 * ui.x;
            pos.y -= float((bit << HEIGHT_BIT) + ADD_OFFSET + DEFAULT_OFFSET);
            float xGui = 0.0;
            float yGui = 0.0;
            float layer = 0.0;
            float opacity = 1.0;
            switch (id) {
                case 1:
                    break;
                case 2:
                    layer = 1.0;
                    break;
                case 3:
                    xGui = ui.x * 100.0 / 100.0;
                    break;
            }
            vertexColor *= vec4(1.0, 1.0, 1.0, opacity);
            pos.x += xGui;
            pos.y += yGui;
            pos.z += layer;
        }
    }

    sphericalVertexDistance = fog_spherical_distance(pos);
    cylindricalVertexDistance = fog_cylindrical_distance(pos);
    texCoord0 = UV0;
    gl_Position = ProjMat * ModelViewMat * vec4(pos, 1.0);
}
