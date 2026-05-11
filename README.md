# FØL Senioradvis

## Intro

This robot is responsible for checking if employees have hit a certain age
and then notifying them and their supervisors.

The robot is split into 3 logical parts one for each relevant department: MBU, MSO, MBA.

## Process arguments

The robot expects process arguments as a json string in the following format:

```json
{
    "departments": ["mbu", "mso", "mba"]
}
```

__departments__: This argument is used to control which parts of the robots should run.
