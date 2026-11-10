import sys
import subprocess
import warnings
import os
import io
import argparse

parser = argparse.ArgumentParser(
    description="LLMPipe: A pipeline tool for calculating MSIC scores using Genomic Language Models."
)

parser.add_argument('-f', '--file', action='store_true', help="Save results to a folder.")
parser.add_argument('-m', '--mafft', action='store_true', help="Align scored sequences.")


model_section = parser.add_argument_group(
    title="Model Options",
    description="Choose which genomic language model to run. If none are specified, PlantCaduceus_l32 is used by default."
)

model_group = model_section.add_mutually_exclusive_group()

model_group.add_argument(
    '-c', '--caduceus', 
    action='store_const', 
    const='kuleshov-group/caduceus-ps_seqlen-131k_d_model-256_n_layer-16', 
    dest='model',
    help="Run the Caduceus model."
)
model_group.add_argument(
    '-p1', '--plantcad1', 
    action='store_const', 
    const='kuleshov-group/PlantCaduceus_l32', 
    dest='model',
    help="Run the PlantCaduceus l32 model."
)
model_group.add_argument(
    '-p2s', '--plantcad2-small', 
    action='store_const', 
    const='kuleshov-group/PlantCAD2-Small-l24-d0768', 
    dest='model',
    help="Run the PlantCAD2 Small model."
)
model_group.add_argument(
    '-p2m', '--plantcad2-medium', 
    action='store_const', 
    const='kuleshov-group/PlantCAD2-Medium-l48-d1024', 
    dest='model',
    help="Run the PlantCAD2 Medium model."
)
model_group.add_argument(
    '-p2l', '--plantcad2-large', 
    action='store_const', 
    const='kuleshov-group/PlantCAD2-Large-l48-d1536', 
    dest='model',
    help="Run the PlantCAD2 Large model."
)

parser.add_argument(
        '-w', '--window', 
        type=int, 
        choices=[512, 1024, 2048, 4096, 8192], 
        default=512,
        help="Specify the model window size in base pairs (e.g., 512, 1024)."
)

parser.add_argument('filepath', type=str, help="Path to the input FASTA file.")

parser.set_defaults(model='kuleshov-group/PlantCaduceus_l32')


args = parser.parse_args()
    
save_to_file = args.file
run_mafft = args.mafft
model_to_run = args.model
window_size = args.window
filepath = args.filepath

import pandas as pd
import numpy as np
from transformers import pipeline, AutoTokenizer, AutoModelForMaskedLM
import gpn.model
import gpn.pipelines
from Bio import SeqIO, BiopythonDeprecationWarning

def is_fasta(filepath):
    try:
        with open(filepath, 'r') as file:
            first_char = file.read(1).strip()
            if first_char == '>':
                return True
            print('File ' + filepath + ' is in the wrong format.\n')
            sys.exit(2)     
        
    except FileNotFoundError:
        print('File ' + filepath + ' does not exist.\n')
        sys.exit(1)

def msic(probs_matrix, probref_vector):
    eps = 1e-9
    probs_matrix = np.clip(probs_matrix, eps, 1.0)
    
    entropy_terms = probs_matrix * (np.log(probs_matrix) / np.log(4))
    _sum = 1.0 + entropy_terms.sum(axis=1)
    
    max_probs = probs_matrix.max(axis=1)
    scaling_factor = 1.0 - 2.0 * ((max_probs - probref_vector) / max_probs)
    
    return scaling_factor * _sum   

pd.set_option('display.max_rows', None)
pd.set_option('display.max_columns', None)
pd.set_option('display.width', None)
pd.set_option('display.max_colwidth', None)

warnings.simplefilter('ignore', FutureWarning)
warnings.simplefilter('ignore', BiopythonDeprecationWarning)
    
if is_fasta(args.filepath):
    filepath = str(args.filepath)

# Test core dependencies
device = 'cuda:0'

# Test PlantCAD model loading

tokenizer = AutoTokenizer.from_pretrained(model_to_run, trust_remote_code=True)
model = AutoModelForMaskedLM.from_pretrained(model_to_run, trust_remote_code=True)
       
model.to(device)

gpn_pipeline = pipeline("gpn", model=model, tokenizer=tokenizer, trust_remote_code=True, device='cuda:0', window_size=window_size)

fasta = list(SeqIO.parse(filepath, "fasta"))
sequence_count = len(fasta)


if run_mafft and sequence_count > 1:  
    command = [
        "mafft",
        "--auto",
        "--thread", "-1",
        "--inputorder",
        filepath    
    ]

    # Align sequences 
    try: 
        mafft_result = subprocess.run(command, capture_output=True, text=True, check=True)
        stream = io.StringIO(mafft_result.stdout)
        aligned_seqs = []
        for record in SeqIO.parse(stream, "fasta"):
            aligned_seqs.append(str(record.seq))
    except subprocess.CalledProcessError as e:
        print(f"Alignment failed: {e}")
        sys.exit(3)

for idx, record in enumerate(fasta):
    df = gpn_pipeline(str(record.seq), batch_size=16)[0]
    header = str(record.description)
    
    # Get rid of GPN Scores
    df = df.drop(columns=["gpn_a", "gpn_c", "gpn_g", "gpn_t"], errors="ignore")  

    # Calculate and add MSIC scores
    probs_matrix = df[["p_a", "p_c", "p_g", "p_t"]].to_numpy()
    probref_vector = df["p_ref"].to_numpy()
        
    df["MSIC"] = msic(probs_matrix, probref_vector)
    df = df.round(4)
    
    if run_mafft and sequence_count > 1:
        columns = ["ref", "p_ref", "p_a", "p_c", "p_g", "p_t", "MSIC"]
        
        # Incorporate alignment into the existing dataframe   
        source_data = df[columns].to_numpy()
        
        col_data = {col: [] for col in columns} 
        
        k = 0
        for char in aligned_seqs[idx]:
            if char != "-":
                row = source_data[k]
                col_data["ref"].append(row[0])
                col_data["p_ref"].append(row[1])
                col_data["p_a"].append(row[2])
                col_data["p_c"].append(row[3])
                col_data["p_g"].append(row[4])
                col_data["p_t"].append(row[5])
                col_data["MSIC"].append(row[6])
                k += 1
            else:
                for col in columns:
                    col_data[col].append(np.nan)
                        
        df = pd.DataFrame(col_data)
        numeric_cols = ["p_ref", "p_a", "p_c", "p_g", "p_t", "MSIC"]
        df[numeric_cols] = df[numeric_cols].apply(pd.to_numeric)
        
    if save_to_file:
        os.makedirs("results", exist_ok=True)
        filename = os.path.basename(filepath).split('.')[0]
        os.makedirs("results/" + filename, exist_ok=True)

        with open(f"results/{filename}/fileIDs.txt", "a") as file:
            file.write(f"{str(idx)}: {header}\n")
        
        # Save csv files
        df.to_csv(f"results/{filename}/{filename}_scores_table{str(idx)}.csv", index=False)    
    
    
print("Script finished.")
