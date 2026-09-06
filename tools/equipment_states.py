"""Extra worn wings and crossbow states for the Java-to-Geyser conversion."""
import json
import shutil

def add_crossbow(g, pack, name):
    states=['','_pulling_0','_pulling_1','_pulling_2','_arrow','_firework']
    geometry={};textures={};
    for i,suffix in enumerate(states):
        model=json.loads(g.resolve_model('orangegames:'+name+suffix).read_text())
        atlas,placement=g.build_atlas(model)
        key='default' if i==0 else ['','crossbow_pulling_0','crossbow_pulling_1','crossbow_pulling_2','crossbow_arrow','crossbow_rocket'][i]
        geo_id='geometry.og.'+name+suffix
        g.write_json(pack/'models/entity'/('og_'+name+suffix+'.geo.json'),g.convert_geometry(model,geo_id,atlas.size,placement))
        tex='textures/attachables/og/'+name+suffix
        atlas.save(pack/(tex+'.png'))
        geometry[key]=geo_id;textures[key]=tex
    att=pack/'attachables'/('og_'+name+'.json')
    data=json.loads(att.read_text());desc=data['minecraft:attachable']['description']
    desc['geometry']=geometry;desc['textures'].update(textures)
    desc['render_controllers']=['controller.render.og.hailstorm']
    keys=list(geometry)
    # Mojang's vanilla crossbow uses query.get_animation_frame: 0 idle,
    # 1..3 pull, 4 loaded arrow, 5 loaded firework.
    g.write_json(pack/'render_controllers/og_hailstorm.json',{'format_version':'1.10.0','render_controllers':{
        'controller.render.og.hailstorm':{
            'arrays':{'geometries':{'array.frames':['geometry.'+k for k in keys]},'textures':{'array.frames':['texture.'+k for k in keys]}},
            'geometry':'array.frames[math.clamp(query.get_animation_frame, 0, 5)]',
            'materials':[{'*':'query.is_enchanted ? material.enchanted : material.default'}],
            'textures':['array.frames[math.clamp(query.get_animation_frame, 0, 5)]','texture.enchanted'],
        }}})
    g.write_json(att,data)

def add_wings(g, pack, name, asset):
    texture='textures/models/armor/og/'+asset+'_wings'
    src=g.REPO/'assets/orangegames/textures/entity/equipment/wings'/(asset+'.png')
    (pack/(texture+'.png')).parent.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(src,pack/(texture+'.png'))
    geometry='geometry.og.'+name+'.wings'
    bones=[{'name':'body','pivot':[0,24,0]}]
    for side in [-1,1]:
        bones.append({'name':'left_wing' if side<0 else 'right_wing','parent':'body','pivot':[side*2,24,2],
                      'rotation':[10,side*12,side*12],'cubes':[{'origin':[-12 if side<0 else 2,4,2],'size':[10,20,2],'uv':[22,0],'mirror':side>0}]})
    g.write_json(pack/'models/entity'/('og_'+name+'_wings.geo.json'),{'format_version':'1.12.0','minecraft:geometry':[
        {'description':{'identifier':geometry,'texture_width':64,'texture_height':32,'visible_bounds_width':3,'visible_bounds_height':3,'visible_bounds_offset':[0,1.5,0]},'bones':bones}]})
    data=g.build_armor_attachable('orangegames:'+name,'CHEST',texture)
    data['minecraft:attachable']['description']['geometry']['default']=geometry
    g.write_json(pack/'attachables'/('og_armor_'+name+'.json'),data)
