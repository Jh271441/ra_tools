# Technical Document: stuck_auto_triage_vlm v3.1 Improvements

## Overview
This document outlines the key improvements made to the stuck_auto_triage_vlm system in version v3.1. The enhancements focus on improving the accuracy of the three-class classification model (correct trigger, false positive, no assistance needed) used in the RA (Remote Assist) system.

## Problem Statement
The initial version of the stuck_auto_triage_vlm model had limited accuracy in classifying RA trigger scenarios, achieving only 58% accuracy on the three-class classification task. This resulted in suboptimal performance in distinguishing between:
- Correct triggers (valid RA requests)
- False positives (unnecessary RA triggers)
- Cases requiring no assistance (normal operation)

## Solution Approach
Two major enhancement techniques were implemented in v3.1:

### 1. Model Fine-Tuning with LoRA
**Technique**: LoRA (Low-Rank Adaptation) fine-tuning based on Qwen3-VL-8B-Instruct model

**Implementation Details**:
- Utilized adapter learning to understand the distribution of mis-triggers, unnecessary assistance cases, and correct triggers
- Applied LoRA technique to efficiently adapt the pre-trained Qwen3-VL-8B-Instruct model
- Training data specifically curated to represent the three-class scenario distribution

**Results**:
- Classification accuracy improved from 58% to 74%
- Significant improvement in correctly identifying the three distinct classes
- More efficient than full model retraining due to LoRA's parameter-efficient approach

### 2. Vision-Grounded Reasoning Distillation
**Technique**: Vision-grounded reasoning distillation using more capable models

**Implementation Details**:
- Leveraged stronger, more capable models to generate reasoning for difficult and ambiguous data samples
- Used the powerful model's reasoning output to enhance the training process
- Replaced original manual reasoning and ops reasoning with enhanced reasoning from the teacher model
- Effectively added implicit Chain-of-Thought (CoT) reasoning to the model

**Results**:
- Further improved classification accuracy from 74% to 79%
- Better handling of complex, edge cases that were previously misclassified
- Enhanced interpretability through improved reasoning chains

## Technical Architecture
```
Input: Visual + Sensor Data
  ↓
Qwen3-VL-8B-Instruct Base Model
  ↓
[LoRA Adapters] - Learn trigger distribution patterns
  ↓
[Visual Grounding Layer] - Apply enhanced reasoning
  ↓
Three-Class Output: {Correct Trigger, False Positive, No Assistance}
```

## Performance Metrics
- **Initial Accuracy**: 58%
- **Post-LoRA Fine-tuning**: 74% (+16 percentage points)
- **Post Vision-Grounded Distillation**: 79% (+5 percentage points from LoRA stage)
- **Overall Improvement**: +21 percentage points from baseline

## Impact
The v3.1 improvements significantly enhance the reliability of the RA auto-triage system:
- Reduced false RA triggers, minimizing unnecessary operator interventions
- Improved identification of genuine stuck scenarios requiring assistance
- Better resource allocation for remote assistance operations
- Enhanced user experience with fewer false alerts

## Future Considerations
- Continue monitoring performance in production environments
- Collect additional edge cases for further model refinement
- Explore ensemble methods to potentially improve accuracy beyond 79%
- Investigate domain adaptation techniques for different driving scenarios

## Conclusion
The v3.1 improvements to stuck_auto_triage_vlm successfully addressed the accuracy limitations of the initial model through a two-stage enhancement process. The combination of LoRA-based fine-tuning and vision-grounded reasoning distillation resulted in a substantial 21 percentage point improvement in classification accuracy, bringing the model to a production-ready 79% accuracy level.