import pygame
import moderngl
import numpy as np
import math
from PIL import Image
import os
import datetime

WINDOW_SIZE = (1280, 720)

WORMHOLE_RHO = 2.0
WORMHOLE_A = 2
WORMHOLE_M = 0.3

class Wormhole3D:
    def __init__(self, window_size):
        self.width, self.height = window_size
        pygame.init()
        pygame.display.gl_set_attribute(pygame.GL_FRAMEBUFFER_SRGB_CAPABLE, 1)
        pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MAJOR_VERSION, 3)
        pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MINOR_VERSION, 3)
        pygame.display.gl_set_attribute(pygame.GL_CONTEXT_PROFILE_MASK, pygame.GL_CONTEXT_PROFILE_CORE)
        pygame.display.set_mode(window_size, pygame.OPENGL | pygame.DOUBLEBUF)
        self.ctx = moderngl.create_context()
        self.program = self.ctx.program(
            vertex_shader=self.get_vertex_shader(),
            fragment_shader=self.get_fragment_shader()
        )
        
        self.camera_pos = np.array([0.0, 0.0, 15.0], dtype='f4')
        self.yaw = math.radians(-90)
        self.pitch = math.radians(0)
        self.speed = 3.0
        
        self.velocity = np.array([0.0, 0.0, 0.0], dtype='f4')
        
        pygame.mouse.set_visible(False)
        pygame.event.set_grab(True)

        self.is_recording = False
        self.frames_buffer = []
        
        try:
            print("Loading skybox for Universe A (from folder 'skybox1')...")
            self.skybox_a_texture = self.load_cubemap('skybox1')
            print("Loading skybox for Universe B (from folder 'skybox2')...")
            self.skybox_b_texture = self.load_cubemap('skybox2')
            self.skybox_a_texture.use(0)
            self.skybox_b_texture.use(1)
            self.program['u_skybox_a'] = 0
            self.program['u_skybox_b'] = 1
        except Exception as e:
            print(f"Error loading Cubemap textures: {e}")
            pygame.quit()
            exit()
            
        self.program['u_resolution'].value = (self.width, self.height)
        self.program['rho'].value = WORMHOLE_RHO
        self.program['a'].value = WORMHOLE_A
        self.program['M_wh'].value = WORMHOLE_M
        vertices = np.array([-1.0, -1.0, 1.0, -1.0, -1.0, 1.0, 1.0, 1.0], dtype='f4')
        vbo = self.ctx.buffer(vertices)
        self.vao = self.ctx.vertex_array(self.program, [(vbo, '2f', 'in_vert')])
        self.clock = pygame.time.Clock()

    def load_cubemap(self, folder_name):
        script_dir = os.path.dirname(os.path.abspath(__file__)) if '__file__' in locals() else os.getcwd()
        skybox_path = os.path.join(script_dir, folder_name)
        if not os.path.isdir(skybox_path):
            raise FileNotFoundError(f"Skybox folder not found: {skybox_path}")
        if folder_name == 'skybox1':
            face_names = ['right.png', 'left.png', 'top.png', 'bottom.png', 'front.png', 'back.png']
        elif folder_name == 'skybox2':
            face_names = ['px.png', 'nx.png', 'py.png', 'ny.png', 'pz.png', 'nz.png']
        else:
            raise ValueError(f"Unknown naming convention for skybox folder '{folder_name}'")
        image_data_list = []
        with Image.open(os.path.join(skybox_path, face_names[0])) as first_img:
            size = first_img.size
        for name in face_names:
            img_path = os.path.join(skybox_path, name)
            with Image.open(img_path).convert("RGBA") as img:
                if img.size != size:
                    img = img.resize(size)
                image_data_list.append(img.tobytes())
        final_image_data = b''.join(image_data_list)
        texture = self.ctx.texture_cube(size, 4, final_image_data)
        texture.filter = (moderngl.LINEAR, moderngl.LINEAR)
        return texture

    def get_vertex_shader(self):
        return """
            #version 330 core
            in vec2 in_vert;
            void main() { gl_Position = vec4(in_vert, 0.0, 1.0); }
        """

    def get_fragment_shader(self):
        return """
            #version 330 core
            out vec4 fragColor;
            uniform vec2 u_resolution;
            uniform samplerCube u_skybox_a;
            uniform samplerCube u_skybox_b;
            uniform vec3 u_camera_pos;
            uniform vec3 u_camera_fwd;
            uniform vec3 u_camera_right;
            uniform vec3 u_camera_up;
            uniform float rho;
            uniform float a;
            uniform float M_wh;
            uniform float u_time; 
            const float PI = 3.1415926535;
            const float DT = 0.05;
            const int MAX_STEPS = 500;
            const float ZOOM = 1.0;
            const float BOUNDARY = 50.0;
            const float FLOW_SPEED = 0.03;
            float LtoR(float l){
                float x = max(0., 2. * (abs(l) - a) / (PI * M_wh));
                return rho + M_wh * (x * atan(x) - 0.5 * log(1. + x * x));
            }
            float LtoDR(float l){
                float x = max(0., 2. * (abs(l) - a) / (PI * M_wh));
                return 2. * atan(x) * sign(l) / PI;
            }
            mat3 rotationY(float angle) {
                float s = sin(angle);
                float c = cos(angle);
                return mat3(c, 0, s, 0, 1, 0, -s, 0, c);
            }
            void main() {
                vec2 uv = (2. * gl_FragCoord.xy - u_resolution.xy) / u_resolution.y;
                vec3 ray_dir = normalize(ZOOM * u_camera_fwd + uv.x * u_camera_right + uv.y * u_camera_up);
                float l = u_camera_pos.z;
                float r = length(u_camera_pos);
                float dl = ray_dir.z;
                float H = r * length(ray_dir.xy);
                float phi = 0.;
                for(int i = 0; i < MAX_STEPS; i++){
                    r = LtoR(l);
                    float dr = LtoDR(l);
                    l += dl * DT;
                    phi += H / (r * r) * DT;
                    dl += H * H * dr / (r * r * r) * DT;
                    if (abs(l) > BOUNDARY) break;
                }
                float dr = LtoDR(l);
                float dx = dl * dr * cos(phi) - H / r * sin(phi);
                float dy = dl * dr * sin(phi) + H / r * cos(phi);
                vec3 final_dir;
                final_dir.z = dx;
                vec2 initial_perp_dir = vec2(0.0);
                if (length(ray_dir.xy) > 1e-5) {
                    initial_perp_dir = normalize(ray_dir.xy);
                }
                final_dir.xy = dy * initial_perp_dir;
                final_dir = normalize(final_dir);
                mat3 rot_a = rotationY(u_time * FLOW_SPEED);
                mat3 rot_b = rotationY(-u_time * FLOW_SPEED * 0.7);
                vec3 rotated_dir_a = rot_a * final_dir;
                vec3 rotated_dir_b = rot_b * final_dir;
                if (l >= 0.0) {
                    fragColor = texture(u_skybox_a, rotated_dir_a);
                } else {
                    fragColor = texture(u_skybox_b, rotated_dir_b);
                }
            }
        """

    def save_gif(self):
        if not self.frames_buffer:
            print("No frames were recorded. Nothing to save.")
            return
        
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filename = f"wormhole_recording_{timestamp}.gif"

        print(f"Saving {len(self.frames_buffer)} frames to {filename}... This may take a moment.")
    
        fps = self.clock.get_fps()
        duration = int(1000 / fps) if fps > 0 else 33 
        
        self.frames_buffer[0].save(
            filename,
            save_all=True,
            append_images=self.frames_buffer[1:],
            optimize=False,
            duration=duration,
            loop=0
        )
        
        print(f"GIF saved successfully: {filename}")
        self.frames_buffer.clear()

    def run(self):
        running = True
        while running:
            dt = self.clock.tick(60) / 1000.0

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        running = False
                    if event.key == pygame.K_w: self.velocity[2] = 1.0
                    if event.key == pygame.K_s: self.velocity[2] = -1.0
                    if event.key == pygame.K_a: self.velocity[0] = -1.0
                    if event.key == pygame.K_d: self.velocity[0] = 1.0
                    if event.key == pygame.K_e: self.velocity[1] = 1.0
                    if event.key == pygame.K_q: self.velocity[1] = -1.0

                if event.type == pygame.KEYUP:
                    if event.key == pygame.K_w and self.velocity[2] == 1.0: self.velocity[2] = 0.0
                    if event.key == pygame.K_s and self.velocity[2] == -1.0: self.velocity[2] = 0.0
                    if event.key == pygame.K_a and self.velocity[0] == -1.0: self.velocity[0] = 0.0
                    if event.key == pygame.K_d and self.velocity[0] == 1.0: self.velocity[0] = 0.0
                    if event.key == pygame.K_e and self.velocity[1] == 1.0: self.velocity[1] = 0.0
                    if event.key == pygame.K_q and self.velocity[1] == -1.0: self.velocity[1] = 0.0
                    
                    if event.key == pygame.K_SPACE:
                        if not self.is_recording:
                            self.is_recording = True
                            self.frames_buffer.clear()
                            print("--- Started recording GIF ---")
                        else:
                            self.is_recording = False
                            print("--- Stopped recording GIF ---")
                            self.save_gif()

            mouse_dx, mouse_dy = pygame.mouse.get_rel()
            self.yaw += mouse_dx * 0.005
            self.pitch -= mouse_dy * 0.005
            self.pitch = max(-math.pi/2 + 0.01, min(self.pitch, math.pi/2 - 0.01))

            cam_fwd = np.array([
                math.cos(self.yaw) * math.cos(self.pitch),
                math.sin(self.pitch),
                math.sin(self.yaw) * math.cos(self.pitch)
            ], dtype='f4')
            
            global_up = np.array([0.0, 1.0, 0.0], dtype='f4')
            cam_right = np.cross(cam_fwd, global_up)
            cam_right /= np.linalg.norm(cam_right)
            
            move_vec = cam_right * self.velocity[0] + global_up * self.velocity[1] + cam_fwd * self.velocity[2]
            self.camera_pos += move_vec * self.speed * dt
            
            cam_up = np.cross(cam_right, cam_fwd)
            
            self.program['u_camera_pos'].value = tuple(self.camera_pos)
            self.program['u_camera_fwd'].value = tuple(cam_fwd)
            self.program['u_camera_right'].value = tuple(cam_right)
            self.program['u_camera_up'].value = tuple(cam_up)
            self.program['u_time'].value = pygame.time.get_ticks() / 1000.0

            self.ctx.clear(0.0, 0.0, 0.0)
            self.vao.render(moderngl.TRIANGLE_STRIP)

            if self.is_recording:

                raw_pixels = self.ctx.screen.read(components=3, alignment=1)

                image = Image.frombytes('RGB', (self.width, self.height), raw_pixels)
                image = image.transpose(Image.FLIP_TOP_BOTTOM)
                self.frames_buffer.append(image)

            pygame.display.flip()
            
            pos = self.camera_pos
            rec_status = "[REC]" if self.is_recording else ""
            pygame.display.set_caption(f"Wormhole Free-Fly {rec_status} - Pos:({pos[0]:.1f}, {pos[1]:.1f}, {pos[2]:.1f}) - FPS: {self.clock.get_fps():.2f}")
            
        pygame.quit()

if __name__ == '__main__':
    sim = Wormhole3D(WINDOW_SIZE)

    sim.run()
