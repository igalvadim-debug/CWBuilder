# H3 Multi-shot Video Generation Workflow

## Overview

This workflow generates a **3-scene video with character consistency and lip-sync audio** using the Minimax H3 model. It demonstrates a complete multi-shot pipeline with:

- **Character consistency** across all 3 scenes
- **Seeded chaining** for temporal coherence (seeds: 1000, 1001, 1002)
- **Audio lip-sync** for each scene
- **Scene transitions** with fade effects
- **Episode assembly** into final video

## Workflow Architecture

### Node Types

1. **H3Director** (Node 1)
   - Main orchestrator for the episode
   - Manages 3-shot scheduling
   - Sets up character reference
   - Configures output parameters

2. **H3MultiShotManager** (Node 2)
   - Processes scenes sequentially
   - Maintains character embedding
   - Chains seeds (1000→1001→1002)
   - Handles scene transitions

3. **H3X2ImageToVideo** (Node 3)
   - Enhanced video generation
   - Upscales latent to full resolution
   - Maintains temporal consistency
   - Handles motion parameters

4. **VAEDecode** (Node 4)
   - Decodes latent to image
   - Converts video frames to pixels

5. **H3EpisodeBuilder** (Node 9)
   - Assembles 3 scenes into final video
   - Applies transitions
   - Merges audio tracks
   - Final video encoding

## Scene Configuration

### Scene 1: Introduction (5 seconds)
- **Prompt**: "A woman with long brown hair wearing a blue dress, smiling warmly at the camera, natural lighting, studio background"
- **Audio**: audio_scene1.wav
- **Seed**: 1000 (base seed)
- **Pose**: standing_greeting
- **Motion bucket**: 127

### Scene 2: Main Content (10 seconds)
- **Prompt**: "The same woman gesturing expressively with hands while speaking, engaged conversation pose, slight head movement"
- **Audio**: audio_scene2.wav
- **Seed**: 1001 (seed + 1)
- **Pose**: speaking_gesturing
- **Motion bucket**: 130

### Scene 3: Conclusion (5 seconds)
- **Prompt**: "The same woman waving goodbye with right hand, friendly closing gesture, soft smile"
- **Audio**: audio_scene3.wav
- **Seed**: 1002 (seed + 2)
- **Pose**: waving_goodbye
- **Motion bucket**: 125

## Character Consistency Pipeline

### Step 1: Reference Extraction (Node 11)
```python
LoadImage(character.png) → H3CharacterReferenceExtractor
  ↓
character_embedding.npy + reference_image
```

**What it does:**
- Extracts face embedding via CLIP/ViT
- Preserves clothing and hair features
- Stores embedding for all 3 shots
- Ensures same character across scenes

### Step 2: Embedding Application (Node 12)
```python
character_embedding → IPAdapterAdvanced
  ↓
applied to each scene generation
```

**Consistency enforcement:**
- Face embedding matching per shot
- Clothing/accessory preservation
- Lighting consistency checks
- Cross-shot alignment

## Audio Lip-sync Process

### Pre-processing
```python
audio_sceneN.wav → LoadAudio
  ↓
- Converted to WAV 44100Hz mono
- Background noise removed
- Volume normalized
```

### Synchronization
```python
audio → VHS_VideoCombine
  ↓
- Pheme detection per frame
- Mouth shapes generated
- Lip animations applied
- Timing offsets calculated
```

## Seed Chaining Strategy

### Purpose
- Maintain temporal consistency
- Avoid abrupt style shifts
- Create smooth transitions
- Preserve character identity

### Implementation
```python
Scene 1: Seed = 1000 (fixed base)
Scene 2: Seed = 1000 + 1 = 1001
Scene 3: Seed = 1001 + 1 = 1002
```

### Advanced: Cross-fade Seeds (Optional)
```python
# Blend seeds at scene boundaries
Scene 1 (last 20%): Blend Seed 1000 → 1001
Scene 2 (first 20%): Blend Seed 1001 → 1002
```

## Required Custom Nodes

### H3 Nodes (Minimax H3)
1. **H3Director** - Episode orchestrator
2. **H3MultiShotManager** - Shot sequencing
3. **H3X2ImageToVideo** - Enhanced generation
4. **H3EpisodeBuilder** - Scene assembly
5. **H3CharacterReferenceExtractor** - Embedding extraction

**Installation:**
```bash
cd ComfyUI/custom_nodes
git clone https://github.com/Comfy-Org/ComfyUI-H3-Director.git
cd ComfyUI-H3-Director
pip install -r requirements.txt
```

### Additional Required Nodes
1. **IPAdapterAdvanced** - Character consistency
2. **CLIPVisionEncode** - Image conditioning
3. **T5TextEncoderFromTransformer** - Text encoding
4. **VHS_VideoCombine** - Video output
5. **SaveImage** - Reference image output

## Model Download Guide

### Diffusion Models
| Model | Directory | Download URL |
|-------|-----------|--------------|
| wan2.2_t2v_14b.safetensors | models/diffusion_models/ | https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged |

### Text Encoders
| Model | Directory | Download URL |
|-------|-----------|--------------|
| umt5_xxl_fp16.safetensors | models/text_encoders/ | https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged |
| clip_l.safetensors | models/text_encoders/ | https://huggingface.co/comfyanonymous/flux_text_encoders |

### VAE
| Model | Directory | Download URL |
|-------|-----------|--------------|
| wan_2.1_vae.safetensors | models/vae/ | https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged |

### IP Adapter
| Model | Directory | Download URL |
|-------|-----------|--------------|
| ipadapter_flux_full.safetensors | models/ip_adapter/ | https://huggingface.co/Comfy-Org/IPAdapter_Flux_ComfyUI_Repackaged |

### Clip Vision
| Model | Directory | Download URL |
|-------|-----------|--------------|
| clip_vision_h.safetensors | models/clip_vision/ | https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged |

## Usage Instructions

### Prerequisites
1. Install ComfyUI with H3 custom nodes
2. Configure H3 API credentials
3. Prepare character image (1024x1024 PNG)
4. Prepare audio files (WAV, 44100Hz, mono)

### Step-by-Step

1. **Load Workflow**
   ```bash
   File → Load → minimax_h3_multishot_3scenes.json
   ```

2. **Configure Character Reference**
   - Replace `character_reference.png` with your character image
   - Node 8: LoadImage
   - Ensure image is high quality (1024x1024 recommended)

3. **Set Audio Files**
   - Node 7: LoadAudio → `audio_scene1.wav`
   - Create additional nodes for scenes 2 and 3
   - Place WAV files in `output/h3_multishot/` directory

4. **Adjust Scene Parameters**
   - Modify prompts in H3MultiShotManager (Node 2)
   - Adjust durations, seeds, motion buckets as needed

5. **Execute**
   - Click "Queue Prompt"
   - Monitor progress
   - Check output directory for results

### Output Files
- `h3_multishot_scene_01.mp4` - Scene 1 (5s)
- `h3_multishot_scene_02.mp4` - Scene 2 (10s)
- `h3_multishot_scene_03.mp4` - Scene 3 (5s)
- `final_episode.mp4` - Combined 20s video with transitions
- `character_embedding_001.npy` - Character embedding file

## Common Issues & Solutions

### Issue: Scene Skipping / Only 1 Segment Generated
**Cause:** H3Director not receiving scene completion signals
**Fix:**
1. Add scene completion callbacks
2. Verify API rate limits
3. Check H3MultiShotManager configuration
4. Ensure all 3 scenes are properly defined in `scenes` array

### Issue: Character Drift Across Scenes
**Cause:** Inconsistent embeddings across shots
**Fix:**
1. Use stronger character reference (increase `consistency_strength` to 0.9)
2. Enable face restoration in H3MultiShotManager
3. Use higher resolution character image (2048x2048)
4. Add IPAdapter for additional consistency

### Issue: Audio Desync
**Cause:** Timing mismatch between audio and video frames
**Fix:**
1. Verify audio sample rate (must be 44100Hz)
2. Adjust `lip_sync_offset` parameter
3. Check audio length matches video duration
4. Re-render with adjusted timing

### Issue: Memory Overflow
**Cause:** Too many high-res frames in GPU memory
**Fix:**
1. Process scenes sequentially (one at a time)
2. Clear cache between shots
3. Use lower resolution for testing (512x512)
4. Reduce `frames` parameter temporarily

### Issue: Character Identity Not Consistent
**Cause:** Weak character embedding extraction
**Fix:**
1. Use clearer character photo (good lighting, frontal view)
2. Increase `character_embedding_mode` strength
3. Add face restoration post-generation
4. Combine with ControlNet for pose consistency

## Quality Assurance Checklist

Before finalizing video:
- [ ] Character identity consistent across all scenes
- [ ] Audio lip-sync accurate within ±2 frames
- [ ] Transitions between scenes smooth (no jump cuts)
- [ ] No frame drops or stuttering
- [ ] Resolution matches target (1280x720 or higher)
- [ ] FPS stable at 24 or 30
- [ ] File size reasonable for distribution
- [ ] Character poses match scene descriptions
- [ ] Lighting consistent across scenes
- [ ] Backgrounds appropriate for each scene

## Performance Optimization

### GPU Memory Management
- Process one scene at a time
- Clear intermediate latents after each scene
- Use lower resolution for testing (512x512)
- Reduce `steps` parameter during testing (15-20)

### API Rate Limiting
- Batch requests when possible
- Implement exponential backoff
- Cache character embeddings
- Use `character_embedding_mode: "extract_and_preserve"`

### Parallel Processing (Advanced)
- Generate scenes independently (if no continuity needed)
- Merge results in EpisodeBuilder
- Use multi-GPU if available

## Testing Workflow

### Phase 1: Single Scene Test
```bash
# Comment out scenes 2 and 3 in H3MultiShotManager
# Run workflow
# Verify:
- Character consistency with reference image
- Audio sync accuracy
- Motion quality
```

### Phase 2: Two Scene Test
```bash
# Enable scenes 1 and 2 only
# Verify seed chaining works
# Check transition quality
# Look for character drift
```

### Phase 3: Full Multi-shot
```bash
# Enable all 3 scenes
# Verify episode assembly
# Check final video quality
# Confirm lip-sync across all scenes
```

## Advanced Customization

### Custom Transitions
```python
# In H3EpisodeBuilder inputs:
transition_type: "dissolve"  # Options: fade, dissolve, cut, wipe
transition_duration_frames: 24  # Adjust transition length
```

### Dynamic Character Pose
```python
# In H3MultiShotManager scenes:
pose: "dynamic"  # Let AI determine pose
pose_control: "openpose"  # Use ControlNet for specific pose
```

### Enhanced Lip-sync
```python
# In H3MultiShotManager scenes:
lip_sync_method: "pheme_detection"  # More accurate
lip_sync_offset: 0.5  # Fine-tune timing (seconds)
```

## Troubleshooting Tips

### Workflow Won't Execute
1. Check custom node installation
2. Verify all required nodes are present
3. Ensure H3 API credentials are configured
4. Test with single scene first

### Generated Video is Stuttering
1. Verify output FPS (should be 24 or 30)
2. Check frame rate consistency
3. Ensure audio/video synchronization
4. Increase `frames` parameter

### Character Looks Different in Each Scene
1. Verify character embedding extraction worked
2. Check IPAdapter strength (should be 0.7-0.9)
3. Ensure same seed base (1000) for all scenes
4. Add face restoration step

### Audio Not Syncing
1. Verify audio file format (WAV, 44100Hz, mono)
2. Check audio duration matches video duration
3. Adjust lip_sync_offset parameter
4. Re-extract embeddings if needed

## Summary

This workflow implements a complete multi-shot video generation pipeline with:
- ✅ 3 scenes with sequential generation
- ✅ Character consistency via embedding preservation
- ✅ Seed chaining (1000 → 1001 → 1002)
- ✅ Audio lip-sync for each scene
- ✅ Scene transitions with fade effects
- ✅ Episode assembly into final video

**Total duration:** 20 seconds (5s + 10s + 5s)
**Resolution:** 1280x720 @ 24fps
**Output format:** MP4 (H.264)
**Audio:** AAC 320kbps

For questions or issues, refer to the documentation or check the H3 custom nodes repository.