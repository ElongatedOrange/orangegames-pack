#version 330

// BetterHud element repositioning ported to the 26.2 consolidated text shader.
// 26.2 merged the rendertype_text* variants into this single file compiled with
// IS_GUI / IS_SEE_THROUGH / IS_GRAYSCALE defines, so the HUD patch must leave
// every non-GUI variant untouched.
#define HEIGHT_BIT 13
#define MAX_BIT 10
#define ADD_OFFSET 4095
#define DEFAULT_OFFSET 10

#if !defined(IS_GUI) && !defined(IS_SEE_THROUGH)
#moj_import <minecraft:fog.glsl>
#moj_import <minecraft:sample_lightmap.glsl>
#endif

#moj_import <minecraft:dynamictransforms.glsl>
#moj_import <minecraft:projection.glsl>
#moj_import <minecraft:globals.glsl>

in vec3 Position;
in vec4 Color;
in vec2 UV0;
#if !defined(IS_GUI) && !defined(IS_SEE_THROUGH)
in ivec2 UV2;

uniform sampler2D Sampler2;

out float sphericalVertexDistance;
out float cylindricalVertexDistance;
#endif

out vec4 vertexColor;
out vec2 texCoord0;

void main() {
    vec3 pos = Position;

#if !defined(IS_GUI) && !defined(IS_SEE_THROUGH)
    vertexColor = Color * sample_lightmap(Sampler2, UV2);
#else
    vertexColor = Color;
#endif

    // BetterHud encodes an element id into the high bits of glyph Y positions.
    // Only decode during the GUI orthographic pass (ProjMat[3].x == -1).
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
            int property = 0;
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
            if ((property & 1) > 0) {
                pos.y += 4.0 * sin((GameTime * 1200.0 + pos.x / ui.x) * 3.1415 * 2.0);
            }
            if ((property & 2) > 0) {
                int hash = int(pos.x) * int(pos.y);
                float time = GameTime * 1200.0;
                hash = 31 * (hash + int(vertexColor.x + time));
                float r = float(hash % 224 + 32) / 255.0;
                hash = 31 * (hash + int(vertexColor.y + time));
                float g = float(hash % 224 + 32) / 255.0;
                hash = 31 * (hash + int(vertexColor.z + time));
                float b = float(hash % 224 + 32) / 255.0;
                float maxValue = max(max(r, g), b);
                vertexColor = vec4(pow(r / maxValue, 3.0), pow(g / maxValue, 3.0), pow(b / maxValue, 3.0), vertexColor.w);
            }
            if ((property & 4) > 0) {
                int hash = int(pos.x) * int(pos.y);
                float time = GameTime * 1200.0;
                hash = 31 * (hash + int(vertexColor.x + time));
                float r = vertexColor.x + float(hash % 64) / 255.0;
                hash = 31 * (hash + int(vertexColor.y + time));
                float g = vertexColor.y + float(hash % 64) / 255.0;
                hash = 31 * (hash + int(vertexColor.z + time));
                float b = vertexColor.z + float(hash % 64) / 255.0;
                vertexColor = vec4(r, g, b, vertexColor.w);
            }
            pos.x += xGui;
            pos.y += yGui;
            pos.z += layer;
        }
    }

#if !defined(IS_GUI) && !defined(IS_SEE_THROUGH)
    sphericalVertexDistance = fog_spherical_distance(pos);
    cylindricalVertexDistance = fog_cylindrical_distance(pos);
#endif

    texCoord0 = UV0;
    gl_Position = ProjMat * ModelViewMat * vec4(pos, 1.0);
}
